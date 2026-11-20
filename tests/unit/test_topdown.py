"""Method (b), the top-down baseline: it learns a toy and never sees a held-out work."""

from __future__ import annotations

import numpy as np
import pytest
from tagging_helpers import cfg, corpus_of, dag_of, labels_of, part, topics_file

from flatatlas.tagging import topdown
from flatatlas.tagging.guard import Guard, HeldOutLeak

pytest.importorskip("sklearn")


def toy(n=60, heldout=()):
    """Regular-language works (a third are DFA works) against combinatorics-on-words works."""
    file = topics_file()
    dag = dag_of(file)
    parts = [part(f"W{i:010d}", f"title {i}") for i in range(n)]
    corpus = corpus_of(parts)
    rng = np.random.default_rng(3)
    vecs = rng.normal(scale=0.05, size=corpus.vectors.shape).astype(np.float32)
    entries = []
    for i in range(n):
        if i % 2 == 0:
            vecs[i, 0] += 1.0
            if i % 6 == 0:
                vecs[i, 2] += 1.0
                labs = ["regular-languages", "deterministic-finite-automata"]
            else:
                labs = ["regular-languages"]
        else:
            vecs[i, 1] += 1.0
            labs = ["combinatorics-on-words"]
        split = "heldout" if parts[i].work_id in heldout else "train"
        entries.append((parts[i].work_id, labs, split, "random"))
    corpus.vectors = vecs
    labels = labels_of(entries)
    return dag, corpus, labels, Guard(labels.gold)


def test_levels_zero_and_one_are_learned() -> None:
    dag, corpus, labels, guard = toy()
    X = topdown.feature_matrix(corpus, dag)
    model = topdown.fit(corpus, dag, labels, guard, cfg(), X, labels.works(split="train"))
    probs = model.predict(X, dag)
    t = dag.index
    # a regular-language DFA work (row 0) vs a words work (row 1)
    assert probs[0][t["regular-languages"]] > 0.8
    assert probs[0][t["deterministic-finite-automata"]] > 0.5
    assert probs[1][t["combinatorics-on-words"]] > 0.8
    assert probs[1][t["regular-languages"]] < 0.2
    # the level-1 probability is the parent's times the child's, so it cannot exceed the parent's
    for row in probs.values():
        assert row[t["deterministic-finite-automata"]] <= row[t["regular-languages"]] + 1e-9


def test_a_held_out_work_is_refused() -> None:
    dag, corpus, labels, guard = toy(heldout=("W0000000003",))
    X = topdown.feature_matrix(corpus, dag)
    with pytest.raises(HeldOutLeak):
        topdown.fit(corpus, dag, labels, guard, cfg(), X, labels.works())
    with pytest.raises(HeldOutLeak):
        topdown.cross_validate(corpus, dag, labels, guard, cfg(), X, labels.works())


def test_cross_validation_scores_every_work_out_of_fold() -> None:
    dag, corpus, labels, guard = toy()
    X = topdown.feature_matrix(corpus, dag)
    works = labels.works(split="train")
    oof = topdown.cross_validate(corpus, dag, labels, guard, cfg(), X, works)
    assert set(oof) == {corpus.index[w] for w in works}
    t = dag.index["regular-languages"]
    right = sum(
        (oof[corpus.index[w]][t] >= 0.5) == (t in {dag.index[x] for x in labels.by_work[w]})
        for w in works
    )
    assert right / len(works) > 0.9


def test_propagation_columns_are_appended() -> None:
    dag, corpus, labels, _ = toy(n=8)
    n_l0 = int((dag.level == 0).sum())
    prop = {
        "prop_cite": np.full((8, dag.n), np.nan),
        "prop_author": np.full((8, dag.n), 0.5),
    }
    X = topdown.feature_matrix(corpus, dag, prop)
    assert X.shape[1] == corpus.vectors.shape[1] + 2 * n_l0
    assert np.all(X[:, corpus.vectors.shape[1] : corpus.vectors.shape[1] + n_l0] == 0.0)  # NaN -> 0
