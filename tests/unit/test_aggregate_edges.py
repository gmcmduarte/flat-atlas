"""The three lateral edge types on toy data worked out by hand (P1-09, D-102)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from flatatlas.aggregate import edges as E
from flatatlas.aggregate.config import BuildsOnConfig, RelatedConfig, SharedCommunityConfig


def test_npmi_by_hand():
    # 4 works; topic a on works {0, 1}, topic b on {0, 1, 2}.
    m = np.array([[1, 1], [1, 1], [0, 1], [0, 0]], dtype=float)
    joint = m.T @ m
    npmi = E.npmi_matrix(joint, m.sum(axis=0), 4.0)
    # p_a = 0.5, p_b = 0.75, p_ab = 0.5: PMI = ln(0.5 / 0.375), NPMI = PMI / -ln(0.5)
    assert npmi[0, 1] == pytest.approx(math.log(0.5 / 0.375) / math.log(2))
    assert npmi[0, 1] == pytest.approx(0.4150375, abs=1e-6)


def test_npmi_extremes():
    # a and b always together on half of the works: NPMI 1; a and c never together: -1
    m = np.array([[1, 1, 0], [1, 1, 0], [0, 0, 1], [0, 0, 1]], dtype=float)
    npmi = E.npmi_matrix(m.T @ m, m.sum(axis=0), 4.0)
    assert npmi[0, 1] == pytest.approx(1.0)
    assert npmi[0, 2] == -1.0


def test_related_edges_need_support_and_skip_ancestor_pairs():
    # 40 works: topics 0 and 1 together on works 0-19, topic 2 alone on 20-39,
    # topic 3 (an ancestor of topic 0 in the mask) copies topic 0.
    m = np.zeros((45, 4))
    m[:20, 0] = m[:20, 1] = m[:20, 3] = 1.0
    m[20:40, 2] = 1.0
    tagged = np.array([True] * 40 + [False] * 5)  # the last five works are not tagged
    exclude = np.eye(4, dtype=bool)
    exclude[0, 3] = exclude[3, 0] = True
    cfg = RelatedConfig(min_support=5, npmi_min=0.1, min_confidence=0.5, bootstrap=50)
    edges = E.related_edges(m, tagged, exclude, cfg, 0.35, seed=1)
    pairs = {(e.src, e.dst) for e in edges}
    assert (0, 1) in pairs
    assert (0, 3) not in pairs  # ancestor pair, although they always co-occur
    assert (0, 2) not in pairs  # never together
    e01 = next(e for e in edges if (e.src, e.dst) == (0, 1))
    # p_0 = p_1 = p_01 = 0.5 on 40 works: NPMI = ln(0.5 / 0.25) / -ln(0.5) = 1.0
    assert e01.weight == pytest.approx(1.0)
    assert e01.evidence["n_both"] == 20 and e01.evidence["n_works"] == 40
    assert e01.confidence == pytest.approx(1.0)  # holds in every resample


def test_related_support_floor():
    m = np.zeros((40, 2))
    m[:4, :] = 0.9  # only 4 works carry both
    cfg = RelatedConfig(min_support=5, npmi_min=0.1, min_confidence=0.0, bootstrap=10)
    assert E.related_edges(m, np.ones(40, bool), np.eye(2, dtype=bool), cfg, 0.35, 1) == []


def test_citation_flow_by_hand():
    # Topics (a, b). Citation 1: u = [0.8, 0], v = [0.1, 0.5]
    #   flow[a, b] = 0.8 * (1 - 0.1) * 0.5 * (1 - 0) = 0.36
    # Citation 2: both works in both topics, which counts for neither direction.
    m = np.array([[0.8, 0.0], [0.1, 0.5], [1.0, 1.0], [1.0, 1.0]])
    flow = E.citation_flow(m, np.array([0, 2]), np.array([1, 3]))
    assert flow[0, 1] == pytest.approx(0.36)
    assert flow[1, 0] == pytest.approx(0.0)
    # the diagonal is never an edge (the mask drops it); its soft value is 0.8*0.9 * 0.1*0.2
    assert flow[0, 0] == pytest.approx(0.0144)
    flow[np.eye(2, dtype=bool)] = 0.0  # as the stage does with its exclusion mask
    assert E.shares(flow)[0, 1] == pytest.approx(1.0)


def test_strata_permutation_stays_inside_strata_and_skips_ineligible():
    strata = np.array([0, 0, 0, 1, 1, 1, 1, 2])
    eligible = np.array([True, True, True, True, True, False, True, True])
    rng = np.random.default_rng(3)
    perm = E.strata_permutation(strata, eligible, rng)
    assert perm[5] == 5 and perm[7] == 7  # not eligible, or alone in its stratum
    for s in (0, 1):
        idx = np.flatnonzero(eligible & (strata == s))
        assert sorted(perm[idx]) == sorted(idx)
    again = E.strata_permutation(strata, eligible, np.random.default_rng(3))
    assert list(perm) == list(again)


def _citing_groups():
    """Three groups of 10 works (topics 0, 1, 2), all in one stratum. Every work of group 0 cites a
    work of group 1."""
    m = np.zeros((30, 3))
    for g in range(3):
        m[g * 10 : (g + 1) * 10, g] = 1.0
    citing = np.arange(0, 10)
    cited = np.arange(10, 20)
    return m, (citing, cited)


def test_builds_on_finds_a_directed_edge_against_the_null():
    m, cites = _citing_groups()
    cfg = BuildsOnConfig(min_flow=5.0, max_p=0.05, permutations=200, stratum_years=5)
    edges = E.builds_on_edges(
        m, np.ones(30, bool), np.full(30, 2000), cites, np.eye(3, dtype=bool), cfg, 0.35, seed=7
    )
    assert [(e.src, e.dst) for e in edges] == [(0, 1)]  # 0 builds on 1, not the reverse
    e = edges[0]
    assert e.evidence["flow"] == pytest.approx(10.0)
    assert e.evidence["n_citations"] == 10
    # Topic 0's whole outflow goes to topic 1 (share 1.0), against about one half in the null.
    assert e.evidence["share"] == pytest.approx(1.0)
    assert 0.3 < e.weight < 0.7
    assert e.confidence > 0.97


def test_builds_on_needs_the_citation_link_to_matter():
    m, cites = _citing_groups()
    cfg = BuildsOnConfig(min_flow=5.0, max_p=0.05, permutations=50, stratum_years=5)
    # Every work in its own stratum: the null cannot shuffle anything, so the null equals the data.
    years = np.arange(30) * 10
    edges = E.builds_on_edges(
        m, np.ones(30, bool), years, cites, np.eye(3, dtype=bool), cfg, 0.35, seed=7
    )
    assert edges == []


def test_cosine_by_hand():
    # Three authors, two topics. Soft sums (author x topic): a0 [2, 1], a1 [1, 2], a2 [1, 1].
    x = np.sqrt(np.array([[2.0, 1.0], [1.0, 2.0], [1.0, 1.0]]))
    cos = E.cosine_matrix(x)
    # t0 . t1 = sqrt2 + sqrt2 + 1, both norms are 2
    assert cos[0, 1] == pytest.approx((2 * math.sqrt(2) + 1) / 4)


def test_shared_community_edge_by_hand():
    # Works w0 [1, 0], w1 [0, 1], w2 [1, 1]; authors a0 on w0 and w2, a1 on w1 and w2, a2 on w2.
    m = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    authorship = (np.array([0, 2, 1, 2, 2]), np.array([0, 0, 1, 1, 2]))
    cfg = SharedCommunityConfig(
        min_shared_authors=3, cosine_min=0.1, min_confidence=0.5, bootstrap=30
    )
    edges = E.shared_community_edges(
        m, np.ones(3, bool), authorship, 3, np.eye(2, dtype=bool), cfg, 0.35, seed=5
    )
    assert len(edges) == 1
    assert (edges[0].src, edges[0].dst) == (0, 1)
    assert edges[0].weight == pytest.approx((2 * math.sqrt(2) + 1) / 4)
    assert edges[0].evidence["n_shared_authors"] == 3
    assert edges[0].confidence == pytest.approx(1.0)


def test_select_top_k():
    def edge(a, b, w):
        return E.Edge(a, b, E.RELATED, w, 1.0, "x")

    edges = [edge(0, 1, 0.9), edge(0, 2, 0.8), edge(0, 3, 0.7), edge(2, 3, 0.6)]
    kept = E.select_top_k(edges, 1, directed=False)
    # topic 0 keeps (0,1); (0,2) and (0,3) are the best of topics 2 and 3, kept by that end
    assert {(e.src, e.dst) for e in kept} == {(0, 1), (0, 2), (0, 3)}
    kept2 = E.select_top_k(edges, 2, directed=False)
    assert (2, 3) in {(e.src, e.dst) for e in kept2}
