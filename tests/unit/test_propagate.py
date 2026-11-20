"""Pass 2: propagation on a 6-node toy graph with known answers (P1-08)."""

from __future__ import annotations

import numpy as np
import pytest

from flatatlas.tagging import propagate
from flatatlas.tagging.config import PropagationConfig
from flatatlas.tagging.pairs import FEATURES, PROP_FEATURES, Pairs

CFG = PropagationConfig(ref_weight=1.0, citer_weight=0.5, influential_boost=2.0, author_window=5)

# Six works, two topics. Pass-1 vectors (probability of topic 0, topic 1):
#   0: (1, 0)   1: (1, 0)   2: (0, 1)   3: (0.5, 0.5)   4: (0, 1)   5: no vector at all
P = np.array([[1, 0], [1, 0], [0, 1], [0.5, 0.5], [0, 1], [0, 0]], dtype=float)
USABLE = np.array([True, True, True, True, True, False])
# Edges (citing -> cited): 3 cites 0, 3 cites 2; 4 cites 3; 0 cites 5 (5 has no vector)
EDGES = [(3, 0, False), (3, 2, False), (4, 3, False), (0, 5, False)]
# Authors: a0 wrote works 0, 1, 2; a1 wrote works 2, 3, 4; work 5 has a2 alone
AUTHORS = [[0], [0], [0, 1], [1], [1], [2]]
YEARS = np.array([2000, 2002, 2010, 2012, 2020, 2000])


def graph(edges=EDGES, years=YEARS) -> propagate.Graph:
    return propagate.build_graph(edges, AUTHORS, years)


def test_prop_cite_weights_references_above_citers() -> None:
    out = propagate.prop_cite(P, USABLE, graph(), CFG)
    # work 3: references 0 and 2 (weight 1 each), citer 4 (weight 0.5)
    expected = (1.0 * P[0] + 1.0 * P[2] + 0.5 * P[4]) / 2.5
    assert out[3] == pytest.approx(expected)
    # work 0: citer 3 only (reference 5 has no vector, so it lends nothing)
    assert out[0] == pytest.approx(P[3])
    # work 4: reference 3 only
    assert out[4] == pytest.approx(P[3])


def test_prop_cite_is_nan_without_a_usable_neighbour() -> None:
    out = propagate.prop_cite(P, USABLE, graph(), CFG)
    assert np.isnan(out[1]).all()  # no edge at all
    # work 0 cites work 5, which has no vector: 5 lends nothing, and 0 still has its citer 3
    only_unusable = propagate.prop_cite(P, USABLE, graph([(0, 5, False)]), CFG)
    assert np.isnan(only_unusable[0]).all()


def test_prop_cite_a_work_without_vector_still_receives() -> None:
    out = propagate.prop_cite(P, USABLE, graph(), CFG)
    # work 5 has no pass-1 vector, but its citer 0 does: it receives P[0] at the citer weight
    assert out[5] == pytest.approx(P[0])


def test_influential_edges_are_boosted() -> None:
    edges = [(3, 0, True), (3, 2, False)]
    out = propagate.prop_cite(P, USABLE, graph(edges), CFG)
    # the edge 3 -> 0 counts twice as much as 3 -> 2
    assert out[3] == pytest.approx((2.0 * P[0] + 1.0 * P[2]) / 3.0)


def test_self_citation_is_ignored() -> None:
    out = propagate.prop_cite(P, USABLE, graph([(2, 2, False)]), CFG)
    assert np.isnan(out[2]).all()


def test_prop_author_excludes_the_work_itself_and_respects_the_window() -> None:
    out = propagate.prop_author(P, USABLE, graph(), CFG)
    # work 0 (2000), author a0: other works 1 (2002, in window) and 2 (2010, out): only work 1
    assert out[0] == pytest.approx(P[1])
    # work 2 (2010), authors a0 and a1. a0: works 0 (2000) and 1 (2002) are out of the window;
    # a1: work 3 (2012) in window, work 4 (2020) out. So only a1 contributes, with work 3.
    assert out[2] == pytest.approx(P[3])
    # work 1 (2002): a0 -> work 0 (2000) in window, work 2 (2010) out
    assert out[1] == pytest.approx(P[0])


def test_prop_author_averages_over_authors() -> None:
    years = np.array([2000, 2000, 2000, 2000, 2000, 2000])
    out = propagate.prop_author(P, USABLE, graph(years=years), CFG)
    # work 2: a0 -> mean(P0, P1) = (1, 0); a1 -> mean(P3, P4) = (0.25, 0.75); mean over authors
    expected = np.mean([P[[0, 1]].mean(axis=0), P[[3, 4]].mean(axis=0)], axis=0)
    assert out[2] == pytest.approx(expected)


def test_prop_author_is_nan_for_a_sole_author_with_nothing_else() -> None:
    out = propagate.prop_author(P, USABLE, graph(), CFG)
    assert np.isnan(out[5]).all()  # a2 wrote nothing else


def test_vectors_from_probs_marks_unusable_rows() -> None:
    Pm, usable = propagate.vectors_from_probs({0: {0: 0.9}, 2: {}}, 4, 3)
    assert Pm[0, 0] == pytest.approx(0.9)
    assert usable.tolist() == [True, False, False, False]


def test_attach_fills_the_two_columns_and_clear_resets_them() -> None:
    n = 2
    pairs = Pairs(
        work=np.array([3, 3]),
        topic=np.array([0, 1]),
        candidate=np.array([True, True]),
        X=np.full((n, len(FEATURES)), np.nan, dtype=np.float32),
        p_noisy=np.zeros(n),
        label=-np.ones(n, dtype=np.int8),
        kind=np.zeros(n, dtype=np.int8),
        parents=[[], []],
    )
    mats = propagate.matrices({r: dict(enumerate(P[r])) for r in range(5)}, graph(), 2, CFG)
    counts = propagate.attach(pairs, mats)
    assert counts["prop_cite"] == 2
    col = FEATURES.index("prop_cite")
    assert pairs.X[0, col] == pytest.approx(mats["prop_cite"][3, 0])
    propagate.clear(pairs)
    assert np.isnan(pairs.X[:, [FEATURES.index(n) for n in PROP_FEATURES]]).all()


def test_one_iteration_only_pass_two_does_not_feed_itself() -> None:
    """Running the matrices twice from the same pass-1 vectors gives the same numbers."""
    probs = {r: dict(enumerate(P[r])) for r in range(5)}
    a = propagate.matrices(probs, graph(), 2, CFG)
    b = propagate.matrices(probs, graph(), 2, CFG)
    for name in a:
        assert np.array_equal(a[name], b[name], equal_nan=True)
