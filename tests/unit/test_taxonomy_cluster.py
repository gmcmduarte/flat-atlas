"""UMAP and HDBSCAN on synthetic blobs (needs the ``ml`` extra; skipped without it)."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("umap")
pytest.importorskip("sklearn")

from flatatlas.taxonomy import cluster as tcluster  # noqa: E402
from flatatlas.taxonomy.config import ClusterConfig  # noqa: E402

CFG = ClusterConfig(
    granularities=[20, 8], min_samples=3, umap_neighbors=10, umap_components=3, label_terms=3
)


def blobs(n_per=30, dim=16, seed=1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    centres = np.eye(dim)[:3] * 5.0
    return np.vstack([c + rng.normal(scale=0.3, size=(n_per, dim)) for c in centres]).astype(
        np.float32
    )


def test_three_separated_blobs_give_three_clusters():
    matrix = blobs()
    assignments, embedding = tcluster.cluster_vectors(matrix, CFG, seed=3)
    assert embedding.shape == (90, 3)
    labels = assignments[20]
    found = {c for c in labels.tolist() if c != -1}
    assert len(found) == 3
    for start in (0, 30, 60):  # each blob lands in one cluster
        block = labels[start : start + 30]
        assert len(set(block.tolist()) - {-1}) == 1


def test_same_seed_same_clusters_and_other_seed_may_differ_in_labels_only():
    matrix = blobs()
    a, ea = tcluster.cluster_vectors(matrix, CFG, seed=3)
    b, eb = tcluster.cluster_vectors(matrix, CFG, seed=3)
    assert all((a[g] == b[g]).all() for g in a)
    assert np.array_equal(ea, eb)


def test_cluster_rows_name_clusters_and_nest_fine_in_coarse():
    matrix = blobs()
    assignments, embedding = tcluster.cluster_vectors(matrix, CFG, seed=3)
    ids = [f"W{i:03d}" for i in range(90)]
    phrase_works = {
        "alpha": {w: 1.0 for w in ids[:30]},
        "beta": {w: 1.0 for w in ids[30:60]},
        "gamma": {w: 1.0 for w in ids[60:]},
    }
    rows, members = tcluster.build_cluster_rows(
        assignments,
        embedding,
        ids,
        phrase_works,
        CFG,
        openalex_primary={w: "T" for w in ids},
        seeds=[{"scheme": "msc", "id": "X", "label": "Alpha things"}],
    )
    coarse = [r for r in rows if r["granularity"] == 20]
    assert sorted(r["label"] for r in coarse) == ["alpha", "beta", "gamma"]
    assert all(r["size"] == 30 for r in coarse)
    assert any(r["seed_matches"] and r["seed_matches"][0]["id"] == "X" for r in coarse)
    assert len(members) == sum(r["size"] for r in rows)
    fine = [r for r in rows if r["granularity"] == 8]
    assert all(r["parent_cluster"] is None or r["parent_cluster"].startswith("g20-") for r in fine)
    assert rows == sorted(rows, key=lambda r: (-r["granularity"], -r["size"], r["cluster_id"]))
