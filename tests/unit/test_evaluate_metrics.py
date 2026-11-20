"""Each metric on synthetic data with a known answer, and the bootstrap against a known value."""

from __future__ import annotations

import numpy as np
import pytest
from tagging_helpers import dag_of, topics_file

from flatatlas.evaluate import metrics as m

DAG = dag_of(topics_file())
RL = DAG.index["regular-languages"]
CW = DAG.index["combinatorics-on-words"]
DFA = DAG.index["deterministic-finite-automata"]


def counts(pred, gold, level=0):
    rows = sorted(gold)
    return m.work_counts(pred, gold, rows, DAG, level)


def test_multi_label_precision_and_recall() -> None:
    # work 0: gold {RL, CW}, predicted {RL}        -> tp RL, fn CW
    # work 1: gold {CW},     predicted {CW, RL}    -> tp CW, fp RL
    # work 2: gold {RL},     predicted {RL}        -> tp RL
    gold = {0: {RL, CW}, 1: {CW}, 2: {RL}}
    pred = {0: {RL}, 1: {CW, RL}, 2: {RL}}
    c = counts(pred, gold)
    p, r, f = m.micro(c)
    assert (c.tp.sum(), c.fp.sum(), c.fn.sum()) == (3, 1, 1)
    assert p == pytest.approx(0.75) and r == pytest.approx(0.75) and f == pytest.approx(0.75)


def test_levels_are_scored_separately_and_derived_parents_do_not_count_at_level_one() -> None:
    gold = {0: {RL, DFA}}
    pred = {0: {RL, DFA}}
    assert m.micro(counts(pred, gold, level=0))[2] == 1.0
    assert m.micro(counts(pred, gold, level=1))[2] == 1.0
    pred_wrong = {0: {RL}}  # the child is missed
    assert m.micro(counts(pred_wrong, gold, level=1)) == (0.0, 0.0, 0.0)


def test_empty_prediction_and_empty_gold_are_zero_not_an_error() -> None:
    assert m.prf(0, 0, 0) == (0.0, 0.0, 0.0)
    assert m.prf(0, 3, 0) == (0.0, 0.0, 0.0)


def test_macro_f1_averages_topics_with_enough_positives() -> None:
    # topic RL: 6 gold positives, all found; topic CW: 6 gold positives, none found (fn)
    gold = {i: {RL} for i in range(6)} | {i: {CW} for i in range(6, 12)}
    pred = {i: {RL} for i in range(6)} | {i: set() for i in range(6, 12)}
    c = counts(pred, gold)
    assert list(m.macro_topics(c)) == sorted([RL, CW])
    assert m.macro_f1(c) == pytest.approx(0.5)  # (1.0 + 0.0) / 2
    thin = counts({0: {RL}}, {0: {RL}})
    assert len(m.macro_topics(thin)) == 0 and np.isnan(m.macro_f1(thin))


def test_resampling_with_repeated_works() -> None:
    gold = {0: {RL}, 1: {RL}}
    pred = {0: {RL}, 1: set()}  # work 0 right, work 1 missed
    c = counts(pred, gold)
    assert m.micro(c, np.array([0, 0, 0]))[2] == 1.0  # three copies of the right work
    assert m.micro(c, np.array([1, 1]))[2] == 0.0


def test_the_bootstrap_interval_covers_a_known_value() -> None:
    # 400 works, each with one gold label RL; each is found with probability 0.7, so the true
    # recall is 0.7 and the 90 % interval over the work sample should contain it.
    rng = np.random.default_rng(5)
    n = 400
    gold = {i: {RL} for i in range(n)}
    pred = {i: ({RL} if rng.random() < 0.7 else set()) for i in range(n)}
    c = counts(pred, gold)
    boot = m.resamples(n, 1000, seed=1)
    est = m.bootstrap({"x": (c, c)}, boot, 0.90)["x"]["r0"]
    assert est.lo < 0.7 < est.hi
    assert est.hi - est.lo < 0.12  # about 2 * 1.645 * sqrt(0.7 * 0.3 / 400)
    assert est.lo <= est.value <= est.hi


def test_a_paired_difference_of_identical_methods_is_exactly_zero() -> None:
    gold = {i: {RL} for i in range(50)}
    pred = {i: ({RL} if i % 3 else set()) for i in range(50)}
    c = counts(pred, gold)
    boot = m.resamples(50, 200, seed=2)
    d = m.paired_difference((c, c), (c, c), boot, 0.90)["mean_f"]
    assert (d.value, d.lo, d.hi) == (0.0, 0.0, 0.0)
    assert not m.excludes_zero(d)


def test_a_clearly_better_method_has_a_paired_interval_that_excludes_zero() -> None:
    n = 200
    gold = {i: {RL} for i in range(n)}
    good = counts({i: {RL} for i in range(n)}, gold)  # always right
    bad = counts({i: ({RL} if i % 2 else set()) for i in range(n)}, gold)  # half missed
    boot = m.resamples(n, 500, seed=3)
    d = m.paired_difference((good, good), (bad, bad), boot, 0.90)["mean_f"]
    assert d.value > 0.2 and m.excludes_zero(d)


def test_the_same_resamples_make_the_difference_tighter_than_two_independent_intervals() -> None:
    rng = np.random.default_rng(9)
    n = 300
    gold = {i: {RL} for i in range(n)}
    base = rng.random(n) < 0.7
    a = counts({i: ({RL} if base[i] else set()) for i in range(n)}, gold)
    flip = rng.random(n) < 0.03  # b differs from a on 3 % of the works
    b = counts({i: ({RL} if base[i] != flip[i] else set()) for i in range(n)}, gold)
    boot = m.resamples(n, 600, seed=4)
    d = m.paired_difference((a, a), (b, b), boot, 0.90)["r0"]
    est = m.bootstrap({"a": (a, a), "b": (b, b)}, boot, 0.90)
    width_single = est["a"]["r0"].hi - est["a"]["r0"].lo
    assert (d.hi - d.lo) < width_single / 2


def test_calibration_curve_bins_stated_against_observed() -> None:
    probs = np.array([0.05, 0.05, 0.95, 0.95, 0.95, 0.95])
    truth = np.array([0, 0, 1, 1, 1, 0])
    curve = m.calibration_curve(probs, truth, bins=10)
    assert [b["n"] for b in curve] == [2, 4]
    assert curve[0]["observed"] == 0.0 and curve[1]["observed"] == pytest.approx(0.75)
    assert curve[1]["stated"] == pytest.approx(0.95)
    assert m.calibration_curve(np.array([1.0]), np.array([1]), bins=10)[0]["hi"] == 1.0
