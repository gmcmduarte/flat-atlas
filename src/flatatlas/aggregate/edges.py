"""The three lateral topic edge types (PLAN §4.3, D-102).

All three work on ``m``, the works x topics matrix of rolled-up confidences
(``membership.roll_up``), and never link a topic to itself, an ancestor or a descendant
(``TopicGraph.related_mask``). The ``confidence`` of an edge says how stable it is under the
method's own resampling, so it is **not comparable across types**:

* ``related``: normalised PMI of soft co-occurrence; confidence = share of bootstrap resamples of
  works in which the edge still meets the support and NPMI floors.
* ``builds-on``: directed citation flow A -> B ("A builds on B", citing work in A and not B, cited
  work in B and not A) against a null that permutes work membership inside strata of publication
  years; confidence = 1 - the empirical p.
* ``shared-community``: cosine of author-activity vectors; confidence = share of bootstrap
  resamples of authors in which the edge still meets the floors.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from flatatlas.aggregate.config import (
    AggregateConfig,
    BuildsOnConfig,
    RelatedConfig,
    SharedCommunityConfig,
)

RELATED = "related"
BUILDS_ON = "builds-on"
SHARED_COMMUNITY = "shared-community"


@dataclass(frozen=True)
class Edge:
    """One edge between topic indices. ``related`` and ``shared-community`` have ``src < dst``."""

    src: int
    dst: int
    edge_type: str
    weight: float
    confidence: float
    method: str
    evidence: dict[str, Any] = field(default_factory=dict)


# -- selection --------------------------------------------------------------------------------


def select_top_k(edges: Sequence[Edge], k: int, *, directed: bool) -> list[Edge]:
    """Keep an edge when it is among the ``k`` strongest of either end.

    Undirected: the strongest ``k`` incident edges of each topic. Directed: the strongest ``k``
    outgoing edges of the source, or the strongest ``k`` incoming edges of the destination.
    Strength is the weight, ties broken by the confidence and then by the topic indices.
    """

    def order(e: Edge) -> tuple[float, float, int, int]:
        return (-e.weight, -e.confidence, e.src, e.dst)

    keep: set[tuple[int, int]] = set()
    by_end: dict[tuple[str, int], list[Edge]] = {}
    for e in edges:
        by_end.setdefault(("out" if directed else "any", e.src), []).append(e)
        by_end.setdefault(("in" if directed else "any", e.dst), []).append(e)
    for group in by_end.values():
        for e in sorted(group, key=order)[:k]:
            keep.add((e.src, e.dst))
    return sorted((e for e in edges if (e.src, e.dst) in keep), key=order)


# -- related ----------------------------------------------------------------------------------


def npmi_matrix(joint: np.ndarray, marginal: np.ndarray, total: float) -> np.ndarray:
    """Normalised PMI from soft counts: ``log(p_ab / (p_a p_b)) / -log(p_ab)``.

    Pairs that never co-occur get -1, and a pair that always co-occurs (``p_ab`` of 1) gets +1.
    """
    p_ab = joint / total
    p_a = marginal / total
    out = np.full(joint.shape, -1.0)
    ok = p_ab > 0
    both_one = p_ab >= 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        pmi = np.log(p_ab / np.outer(p_a, p_a))
        norm = pmi / -np.log(p_ab)
    out[ok] = norm[ok]
    out[both_one] = 1.0
    return out


def related_edges(
    m: np.ndarray,
    tagged: np.ndarray,
    exclude: np.ndarray,
    cfg: RelatedConfig,
    present_min: float,
    seed: int,
) -> list[Edge]:
    """``related`` edges on the works with a normal tag (``tagged`` is a boolean per work)."""
    mt = m[tagged].astype(np.float64)
    n_works = mt.shape[0]
    if n_works == 0:
        return []
    present = (mt >= present_min).astype(np.float64)
    joint = mt.T @ mt
    marginal = mt.sum(axis=0)
    support = present.T @ present
    npmi = npmi_matrix(joint, marginal, float(n_works))

    def passes(npmi_b: np.ndarray, support_b: np.ndarray) -> np.ndarray:
        return (support_b >= cfg.min_support) & (npmi_b >= cfg.npmi_min)

    holds = np.zeros(joint.shape)
    rng = np.random.default_rng(seed)
    uniform = np.full(n_works, 1.0 / n_works)
    for _ in range(cfg.bootstrap):
        c = rng.multinomial(n_works, uniform).astype(np.float64)
        joint_b = (mt * c[:, None]).T @ mt
        support_b = (present * c[:, None]).T @ present
        npmi_b = npmi_matrix(joint_b, c @ mt, float(n_works))
        holds += passes(npmi_b, support_b)
    confidence = holds / cfg.bootstrap

    edges = []
    n_topics = m.shape[1]
    for a in range(n_topics):
        for b in range(a + 1, n_topics):
            if exclude[a, b] or not passes(npmi[a, b], support[a, b]):
                continue
            if confidence[a, b] < cfg.min_confidence:
                continue
            edges.append(
                Edge(
                    a,
                    b,
                    RELATED,
                    float(npmi[a, b]),
                    float(confidence[a, b]),
                    "npmi-bootstrap-v1",
                    {
                        "n_both": int(support[a, b]),
                        "n_a": int(present[:, a].sum()),
                        "n_b": int(present[:, b].sum()),
                        "n_works": n_works,
                        "soft_both": round(float(joint[a, b]), 4),
                    },
                )
            )
    return edges


# -- builds-on --------------------------------------------------------------------------------


def citation_flow(m: np.ndarray, citing: np.ndarray, cited: np.ndarray) -> np.ndarray:
    """Exclusive citation flow between topics.

    ``flow[a, b] = sum over citations (u, v) of m[u, a] (1 - m[v, a]) * m[v, b] (1 - m[u, b])``:
    the citing work is in *a* and the cited work is in *b*, and a citation whose two ends both
    belong to both topics counts for neither. Without the second part, two topics that share
    works would "build on" each other just because those works cite one another.
    """
    mu = m[citing].astype(np.float64)
    mv = m[cited].astype(np.float64)
    return (mu * (1.0 - mv)).T @ (mv * (1.0 - mu))


def shares(flow: np.ndarray) -> np.ndarray:
    """Row shares: the part of each topic's outgoing flow that goes to each other topic."""
    out = flow.sum(axis=1, keepdims=True)
    return np.divide(flow, out, out=np.zeros_like(flow), where=out > 0)


def strata_permutation(strata: np.ndarray, eligible: np.ndarray, rng: np.random.Generator):
    """Index array that shuffles eligible works inside their stratum; the others stay in place."""
    perm = np.arange(len(strata))
    for s in np.unique(strata[eligible]):
        idx = np.flatnonzero(eligible & (strata == s))
        perm[idx] = rng.permutation(idx)
    return perm


def builds_on_edges(
    m: np.ndarray,
    tagged: np.ndarray,
    years: np.ndarray,
    cites: tuple[np.ndarray, np.ndarray],
    exclude: np.ndarray,
    cfg: BuildsOnConfig,
    present_min: float,
    seed: int,
) -> list[Edge]:
    """Directed ``builds-on`` edges (``src`` builds on ``dst``) from work-level citations.

    ``cites`` holds the indices of the citing and the cited works. Only citations between works
    with a normal tag are used, and only those works are shuffled in the null model.
    """
    citing, cited = cites
    keep = tagged[citing] & tagged[cited] & (citing != cited)
    citing, cited = citing[keep], cited[keep]
    n_topics = m.shape[1]
    if len(citing) == 0:
        return []
    flow = citation_flow(m, citing, cited)
    flow[exclude] = 0.0
    obs_share = shares(flow)
    strata = (years.astype(int) // cfg.stratum_years).astype(int)
    rng = np.random.default_rng(seed)
    ge = np.zeros((n_topics, n_topics))
    share_sum = np.zeros((n_topics, n_topics))
    flow_sum = np.zeros((n_topics, n_topics))
    for _ in range(cfg.permutations):
        perm = strata_permutation(strata, tagged, rng)
        f = citation_flow(m, perm[citing], perm[cited])
        f[exclude] = 0.0
        ge += f >= flow - 1e-9
        share_sum += shares(f)
        flow_sum += f
    p = (1.0 + ge) / (1.0 + cfg.permutations)
    weight = obs_share - share_sum / cfg.permutations
    expected = flow_sum / cfg.permutations
    hard = (m[citing] >= present_min).astype(np.float64).T @ (m[cited] >= present_min)
    edges = []
    for a in range(n_topics):
        for b in range(n_topics):
            if exclude[a, b] or flow[a, b] < cfg.min_flow:
                continue
            if p[a, b] > cfg.max_p or weight[a, b] <= 0:
                continue
            edges.append(
                Edge(
                    a,
                    b,
                    BUILDS_ON,
                    float(weight[a, b]),
                    float(1.0 - p[a, b]),
                    "citation-flow-permutation-v1",
                    {
                        "flow": round(float(flow[a, b]), 4),
                        "expected_flow": round(float(expected[a, b]), 4),
                        "n_citations": int(hard[a, b]),
                        "share": round(float(obs_share[a, b]), 4),
                        "p": round(float(p[a, b]), 5),
                        "permutations": cfg.permutations,
                    },
                )
            )
    return edges


# -- shared-community ---------------------------------------------------------------------------


def cosine_matrix(x: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
    """Cosine between the columns of ``x`` (rows may carry resampling weights)."""
    w = np.ones(x.shape[0]) if weights is None else weights
    gram = (x * w[:, None]).T @ x
    norm = np.sqrt(np.diag(gram))
    denom = np.outer(norm, norm)
    return np.divide(gram, denom, out=np.zeros_like(gram), where=denom > 0)


def shared_community_edges(
    m: np.ndarray,
    tagged: np.ndarray,
    authorship: tuple[np.ndarray, np.ndarray],
    n_authors: int,
    exclude: np.ndarray,
    cfg: SharedCommunityConfig,
    present_min: float,
    seed: int,
) -> list[Edge]:
    """``shared-community`` edges from author activity on the works with a normal tag.

    ``authorship`` holds ``(work index, author index)`` pairs, each pair once. An author's activity
    in a topic is the square root of the sum of the rolled-up confidences of their papers there.
    """
    work_idx, author_idx = authorship
    keep = tagged[work_idx]
    work_idx, author_idx = work_idx[keep], author_idx[keep]
    soft = np.zeros((n_authors, m.shape[1]))
    np.add.at(soft, author_idx, m[work_idx].astype(np.float64))
    active = soft.sum(axis=1) > 0
    soft = soft[active]
    if soft.shape[0] == 0:
        return []
    x = np.sqrt(soft)
    present = (soft >= present_min).astype(np.float64)
    shared = present.T @ present
    cos = cosine_matrix(x)

    def passes(cos_b: np.ndarray, shared_b: np.ndarray) -> np.ndarray:
        return (shared_b >= cfg.min_shared_authors) & (cos_b >= cfg.cosine_min)

    holds = np.zeros(cos.shape)
    rng = np.random.default_rng(seed)
    n = x.shape[0]
    uniform = np.full(n, 1.0 / n)
    for _ in range(cfg.bootstrap):
        c = rng.multinomial(n, uniform).astype(np.float64)
        holds += passes(cosine_matrix(x, c), (present * c[:, None]).T @ present)
    confidence = holds / cfg.bootstrap

    edges = []
    for a in range(m.shape[1]):
        for b in range(a + 1, m.shape[1]):
            if exclude[a, b] or not passes(cos[a, b], shared[a, b]):
                continue
            if confidence[a, b] < cfg.min_confidence:
                continue
            edges.append(
                Edge(
                    a,
                    b,
                    SHARED_COMMUNITY,
                    float(cos[a, b]),
                    float(confidence[a, b]),
                    "author-cosine-bootstrap-v1",
                    {
                        "n_shared_authors": int(shared[a, b]),
                        "n_authors_a": int(present[:, a].sum()),
                        "n_authors_b": int(present[:, b].sum()),
                        "n_authors": int(n),
                    },
                )
            )
    return edges


def compute_edges(
    m: np.ndarray,
    tagged: np.ndarray,
    years: np.ndarray,
    cites: tuple[np.ndarray, np.ndarray],
    authorship: tuple[np.ndarray, np.ndarray],
    n_authors: int,
    exclude: np.ndarray,
    cfg: AggregateConfig,
) -> dict[str, list[Edge]]:
    """All three edge types, each cut to the strongest ``top_k`` per topic."""
    rel = related_edges(m, tagged, exclude, cfg.related, cfg.present_min, cfg.seed + 1)
    bld = builds_on_edges(
        m, tagged, years, cites, exclude, cfg.builds_on, cfg.present_min, cfg.seed + 2
    )
    com = shared_community_edges(
        m,
        tagged,
        authorship,
        n_authors,
        exclude,
        cfg.shared_community,
        cfg.present_min,
        cfg.seed + 3,
    )
    return {
        RELATED: select_top_k(rel, cfg.top_k, directed=False),
        BUILDS_ON: select_top_k(bld, cfg.top_k, directed=True),
        SHARED_COMMUNITY: select_top_k(com, cfg.top_k, directed=False),
    }
