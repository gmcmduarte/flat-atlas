"""``taxonomy cluster``: UMAP + HDBSCAN on SPECTER2 vectors at three granularities (PLAN §9.1
step 3), c-TF-IDF labels, and the overlap of clusters with the seeds.

* The vectors are one per work (``local_work_embedding``): Semantic Scholar's SPECTER2 vector when
  there is one, a local one otherwise.
* UMAP (cosine, ``random_state`` fixed) reduces to a few dimensions; HDBSCAN then runs at each
  ``min_cluster_size`` of the config. Points HDBSCAN calls noise belong to no cluster.
* A cluster's label is its top phrases by c-TF-IDF over the clusters of that granularity, using the
  mined phrase vocabulary, so labels and candidate topics speak the same words.
* Nesting across granularities: a finer cluster whose members mostly (``NEST_SHARE``) lie in one
  coarser cluster is its child (evidence (d) of PLAN §9.1 step 4).

``umap-learn`` and scikit-learn are in the ``ml`` extra and are imported only when clustering runs.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from flatatlas.taxonomy.config import ClusterConfig
from flatatlas.taxonomy.phrases import key_tokens

NEST_SHARE = 0.6
MAX_EXAMPLES = 5
TOP_OPENALEX = 3


def cluster_vectors(
    matrix: np.ndarray, cfg: ClusterConfig, seed: int
) -> tuple[dict[int, np.ndarray], np.ndarray]:
    """Cluster assignments (``-1`` is noise) for each granularity, and the UMAP embedding."""
    try:
        import umap
        from sklearn.cluster import HDBSCAN
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise RuntimeError(
            "clustering needs the ml extra: run `uv sync --extra ml` (umap-learn, scikit-learn)"
        ) from exc
    reducer = umap.UMAP(
        n_neighbors=cfg.umap_neighbors,
        n_components=cfg.umap_components,
        min_dist=cfg.umap_min_dist,
        metric="cosine",
        random_state=seed,
        n_jobs=1,
        compatibility_layout=True,  # the 0.5 pipeline, named so a new default cannot change runs
    )
    embedding = reducer.fit_transform(matrix)
    out: dict[int, np.ndarray] = {}
    for size in cfg.granularities:
        model = HDBSCAN(min_cluster_size=size, min_samples=cfg.min_samples, copy=True)
        out[size] = model.fit_predict(embedding)
    return out, embedding


def cluster_id(granularity: int, label: int) -> str:
    return f"g{granularity}-c{label}"


def nest(
    coarse: np.ndarray, fine: np.ndarray, coarse_g: int, fine_g: int
) -> dict[str, tuple[str, float]]:
    """``fine cluster id -> (coarse cluster id, share of its members inside it)`` when the share
    reaches ``NEST_SHARE``."""
    parents: dict[str, tuple[str, float]] = {}
    for label in sorted(set(fine.tolist()) - {-1}):
        members = np.flatnonzero(fine == label)
        counts = Counter(int(c) for c in coarse[members] if c != -1)
        if not counts:
            continue
        top, n = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        share = n / len(members)
        if share >= NEST_SHARE:
            parents[cluster_id(fine_g, int(label))] = (cluster_id(coarse_g, top), round(share, 3))
    return parents


def label_clusters(
    assignment: np.ndarray,
    work_ids: Sequence[str],
    phrase_works: Mapping[str, Mapping[str, float]],
    n_terms: int,
) -> dict[int, list[tuple[str, float]]]:
    """Top ``n_terms`` phrases of each cluster by c-TF-IDF (classes are the clusters).

    ``phrase_works`` maps a phrase key to ``{work_id: weight}``. ``tf`` is the weighted number of a
    cluster's works that hold the phrase, ``f_t`` its count over all clusters and ``A`` the mean
    cluster total. A phrase contained in a better-scored phrase of the label is skipped.
    """
    position = {w: i for i, w in enumerate(work_ids)}
    labels = sorted(set(assignment.tolist()) - {-1})
    tf: dict[str, Counter[int]] = {}
    for key, works in phrase_works.items():
        counter: Counter[int] = Counter()
        for wid, weight in works.items():
            i = position.get(wid)
            if i is not None and assignment[i] != -1:
                counter[int(assignment[i])] += min(1.0, weight)
        if counter:
            tf[key] = counter
    if not labels or not tf:
        return {}
    totals = {c: sum(counter.get(c, 0.0) for counter in tf.values()) for c in labels}
    mean_total = sum(totals.values()) / len(labels)
    out: dict[int, list[tuple[str, float]]] = {}
    for c in labels:
        scored = []
        for key, counter in tf.items():
            if counter.get(c, 0.0) <= 0:
                continue
            f_t = sum(counter.values())
            scored.append((counter[c] * math.log(1 + mean_total / f_t), key))
        scored.sort(key=lambda t: (-t[0], t[1]))
        chosen: list[tuple[str, float]] = []
        for score, key in scored:
            if any(key in kept or kept in key for kept, _ in chosen):
                continue
            chosen.append((key, round(score, 3)))
            if len(chosen) == n_terms:
                break
        out[c] = chosen
    return out


def seed_overlap(
    terms: Sequence[str], seeds: Sequence[Mapping[str, str]], min_jaccard: float = 0.34
) -> list[dict[str, Any]]:
    """Seed entries (``scheme``, ``id``, ``label``) whose label words overlap the cluster's terms.

    A lexical overlap: Jaccard between the key tokens of the terms and of the seed label. It says
    which seed a cluster resembles by name, not by its works (the works carry no CCS or MSC codes).
    """
    cluster_tokens = {t for term in terms for t in term.split()}
    hits = []
    for seed in seeds:
        seed_tokens = set(key_tokens(seed["label"]))
        if not seed_tokens or not cluster_tokens:
            continue
        jac = len(cluster_tokens & seed_tokens) / len(cluster_tokens | seed_tokens)
        if jac >= min_jaccard:
            hits.append({**seed, "jaccard": round(jac, 3)})
    hits.sort(key=lambda h: (-h["jaccard"], h["scheme"], h["id"]))
    return hits[:3]


def centroid_examples(
    embedding: np.ndarray, members: np.ndarray, work_ids: Sequence[str], n: int = MAX_EXAMPLES
) -> list[str]:
    """The ``n`` works closest to the cluster centre in the reduced space (ties by work ID)."""
    centre = embedding[members].mean(axis=0)
    dist = np.linalg.norm(embedding[members] - centre, axis=1)
    order = sorted(
        range(len(members)), key=lambda i: (round(float(dist[i]), 6), work_ids[members[i]])
    )
    return [work_ids[members[i]] for i in order[:n]]


def build_cluster_rows(
    assignments: Mapping[int, np.ndarray],
    embedding: np.ndarray,
    work_ids: Sequence[str],
    phrase_works: Mapping[str, Mapping[str, float]],
    cfg: ClusterConfig,
    *,
    openalex_primary: Mapping[str, str],
    seeds: Sequence[Mapping[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rows for ``clusters.parquet`` and ``cluster_members.parquet``."""
    grans = sorted(assignments, reverse=True)  # coarse (large min size) to fine
    rows: list[dict[str, Any]] = []
    members_rows: list[dict[str, Any]] = []
    parents: dict[str, tuple[str, float]] = {}
    for coarse_g, fine_g in zip(grans, grans[1:], strict=False):
        parents.update(nest(assignments[coarse_g], assignments[fine_g], coarse_g, fine_g))
    for g in grans:
        assignment = assignments[g]
        labels = label_clusters(assignment, work_ids, phrase_works, cfg.label_terms)
        for c in sorted(set(assignment.tolist()) - {-1}):
            members = np.flatnonzero(assignment == c)
            cid = cluster_id(g, int(c))
            terms = [t for t, _ in labels.get(int(c), [])]
            topics = Counter(openalex_primary.get(work_ids[i], "(none)") for i in members)
            rows.append(
                {
                    "cluster_id": cid,
                    "granularity": g,
                    "size": int(len(members)),
                    "label": ", ".join(terms),
                    "terms": terms,
                    "parent_cluster": parents.get(cid, (None, None))[0],
                    "parent_share": parents.get(cid, (None, None))[1],
                    "openalex_topics": [
                        {"name": name, "share": round(n / len(members), 3)}
                        for name, n in sorted(topics.items(), key=lambda kv: (-kv[1], kv[0]))[
                            :TOP_OPENALEX
                        ]
                    ],
                    "seed_matches": seed_overlap(terms, seeds),
                    "examples": centroid_examples(embedding, members, work_ids),
                }
            )
            members_rows.extend(
                {"cluster_id": cid, "granularity": g, "work_id": work_ids[i]} for i in members
            )
    rows.sort(key=lambda r: (-r["granularity"], -r["size"], r["cluster_id"]))
    members_rows.sort(key=lambda r: (r["cluster_id"], r["work_id"]))
    return rows, members_rows


def phrase_work_weights(
    stats: Mapping[str, Any], vocabulary: set[str]
) -> dict[str, dict[str, float]]:
    """``phrase key -> {work_id: weight}`` for the mined vocabulary (from ``PhraseStats``)."""
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for key in sorted(vocabulary):
        s = stats.get(key)
        if s is not None:
            out[key] = dict(s.weights)
    return dict(out)
