"""Fusion, selection, the leak rule and the held-out guard (P1-07, PLAN §9.4)."""

from __future__ import annotations

import numpy as np
import pytest
from tagging_helpers import cfg, corpus_of, dag_of, labels_of, part, topics_file

from flatatlas.tagging import noisyor
from flatatlas.tagging.config import SIGNALS
from flatatlas.tagging.fusion import check_trainable, fit_two_stage, select_tags
from flatatlas.tagging.guard import Guard, HeldOutLeak
from flatatlas.tagging.inputs import Corpus
from flatatlas.tagging.pairs import (
    FEATURES,
    KIND_GOLD_RANDOM,
    KIND_GOLD_TOPUP,
    KIND_SILVER,
    SILVER_DEFINING,
    Pairs,
    assign_silver,
)
from flatatlas.tagging.signals import Signals

# -- method (a) -----------------------------------------------------------------------------------


def mats(**values) -> dict[str, np.ndarray]:
    return {name: np.full((1, 1), values.get(name, np.nan)) for name in SIGNALS}


def p_of(**values) -> float:
    return float(noisyor.noisy_or(mats(**values), cfg())[0, 0])


@pytest.mark.parametrize("name", SIGNALS)
def test_noisy_or_never_decreases_when_a_signal_grows(name):
    grid = [0.0, 0.2, 0.5, 0.8, 0.95, 1.0]
    base = {"lex_title": 0.3, "emb_seed": 0.95, "src_openalex": 0.4}
    ps = [p_of(**{**base, name: v}) for v in grid]
    assert all(b >= a - 1e-12 for a, b in zip(ps, ps[1:], strict=False))
    assert all(0.0 <= p <= 1.0 for p in ps)


def test_missing_signals_count_as_zero():
    assert p_of() == 0.0
    assert p_of(lex_title=0.8) == pytest.approx(p_of(lex_title=0.8, lex_refs=np.nan))


def test_agreement_bonus_needs_two_independent_families():
    c = cfg()
    one_family = p_of(lex_title=1.0, lex_refs=1.0)  # both lexical
    c0 = c.model_copy(deep=True)
    c0.noisy_or.agreement.bonus = 0.0
    no_bonus = float(noisyor.noisy_or(mats(lex_title=1.0, lex_refs=1.0), c0)[0, 0])
    assert one_family == pytest.approx(no_bonus)
    two = p_of(lex_title=1.0, emb_seed=1.0)
    no_bonus_two = float(noisyor.noisy_or(mats(lex_title=1.0, emb_seed=1.0), c0)[0, 0])
    assert two > no_bonus_two


# -- selection ------------------------------------------------------------------------------------


def dag():
    return dag_of(topics_file())


def test_selection_adds_ancestors_as_derived_rows_and_marks_one_primary():
    d = dag()
    t = d.index
    prob = {t["deterministic-finite-automata"]: 0.8, t["regular-languages"]: 0.3}
    sel = select_tags(prob, d, threshold=0.35, max_topics=6, fallback_min=0.15)
    by_topic = {topic: (conf, derived) for topic, conf, derived in sel.rows}
    assert by_topic[t["deterministic-finite-automata"]] == (0.8, False)
    assert by_topic[t["regular-languages"]][1] is True  # the ancestor is derived
    assert by_topic[t["regular-languages"]][0] == pytest.approx(0.8)  # at least the child's
    assert sel.primary == t["deterministic-finite-automata"]


def test_selection_tags_the_parent_when_only_the_parent_is_supported():
    d = dag()
    t = d.index
    sel = select_tags(
        {t["regular-languages"]: 0.7}, d, threshold=0.35, max_topics=6, fallback_min=0.15
    )
    assert [(topic, derived) for topic, _c, derived in sel.rows] == [
        (t["regular-languages"], False)
    ]


def test_selection_keeps_at_most_the_maximum_number_of_non_derived_topics():
    d = dag()
    prob = {i: 0.9 - 0.1 * i for i in range(d.n)}
    sel = select_tags(prob, d, threshold=0.35, max_topics=2, fallback_min=0.15)
    assert sum(1 for _t, _c, derived in sel.rows if not derived) <= 2


def test_selection_falls_back_to_the_best_level0_topic_or_leaves_the_work_untagged():
    d = dag()
    t = d.index
    low = select_tags(
        {t["regular-languages"]: 0.2, t["combinatorics-on-words"]: 0.1},
        d,
        threshold=0.35,
        max_topics=6,
        fallback_min=0.15,
    )
    assert low.low_confidence and low.rows[0][0] == t["regular-languages"]
    none = select_tags(
        {t["regular-languages"]: 0.05}, d, threshold=0.35, max_topics=6, fallback_min=0.15
    )
    assert none.untagged and none.rows == []


# -- the leak rule and the guard ----------------------------------------------------------------


def silver_fixture():
    d = dag()
    t = d.index
    parts = [part("W0000000001", "x"), part("W0000000002", "y")]
    corpus = corpus_of(parts)
    labels = labels_of([("W0000000002", ["regular-languages"], "train", "random")])
    shape = (2, d.n)
    m = {name: np.full(shape, np.nan, dtype=np.float32) for name in SIGNALS}
    m["lex_title"][:] = 0.0
    m["lex_title"][0, t["deterministic-finite-automata"]] = 1.0
    m["src_openalex"][0, t["deterministic-finite-automata"]] = 0.8
    m["src_openalex"][0, t["combinatorics-on-words"]] = 0.0
    sig = Signals(m, {})
    rows = [0, 0, 0, 1]
    topics = [t["deterministic-finite-automata"], t["combinatorics-on-words"], t["avoidability"], 0]
    X = np.full((4, len(FEATURES)), 0.5, dtype=np.float32)
    pairs = Pairs(
        np.array(rows), np.array(topics), np.ones(4, bool), X, np.zeros(4),
        -np.ones(4, dtype=np.int8), np.zeros(4, dtype=np.int8), [[] for _ in range(4)],
    )  # fmt: skip
    return d, corpus, labels, sig, pairs


def test_silver_pairs_hide_the_signals_that_defined_them():
    d, corpus, labels, sig, pairs = silver_fixture()
    assign_silver(pairs, sig, d, corpus, labels, cfg())
    pos, neg = 0, 1
    assert pairs.label[pos] == 1 and pairs.kind[pos] == KIND_SILVER
    assert pairs.label[neg] == 0 and pairs.kind[neg] == KIND_SILVER
    for i in (pos, neg):
        for col in SILVER_DEFINING:
            assert np.isnan(pairs.X[i, FEATURES.index(col)])  # the leak rule
        assert not np.isnan(pairs.X[i, FEATURES.index("emb_seed")])  # other signals stay
    assert pairs.kind[3] == 0 and pairs.label[3] == -1  # gold works get no silver label
    assert not np.isnan(pairs.X[3, FEATURES.index("lex_title")])


def synthetic(n_works=70, seed=0, heldout=()):
    rng = np.random.default_rng(seed)
    ids = [f"W{i:010d}" for i in range(n_works)]
    corpus = Corpus(ids, {w: i for i, w in enumerate(ids)}, [], np.zeros((n_works, 2)),
                    np.ones(n_works, dtype=np.int8), [""] * n_works, [{} for _ in ids])  # fmt: skip
    rows, X, label, kind, parents = [], [], [], [], []
    for w in range(n_works):
        for level in (0, 1):
            y = int(rng.random() < 0.4)
            f = rng.normal(size=len(FEATURES)).astype(np.float32)
            f[FEATURES.index("lex_title")] = 0.9 * y + 0.1 * rng.random()
            f[FEATURES.index("emb_seed")] = (
                np.nan if rng.random() < 0.2 else 0.5 * y + 0.5 * rng.random()
            )
            rows.append(w)
            X.append(f)
            label.append(y)
            kind.append(KIND_GOLD_RANDOM if w < 45 else KIND_GOLD_TOPUP if w < 55 else KIND_SILVER)
            parents.append([] if level == 0 else [len(rows) - 2])
    pairs = Pairs(
        np.array(rows), np.array([i % 2 for i in range(len(rows))]), np.ones(len(rows), bool),
        np.array(X), np.zeros(len(rows)), np.array(label, dtype=np.int8),
        np.array(kind, dtype=np.int8), parents,
    )  # fmt: skip
    entries = []
    for w in range(55):
        split = "heldout" if ids[w] in heldout else "train"
        entries.append((ids[w], ["regular-languages"], split, "random"))
    return corpus, pairs, Guard(labels_of(entries).gold)


def test_every_fit_refuses_a_held_out_work():
    corpus, pairs, guard = synthetic(heldout=("W0000000003",))
    with pytest.raises(HeldOutLeak):
        check_trainable(pairs, corpus, guard, purpose="test")
    pytest.importorskip("sklearn")
    with pytest.raises(HeldOutLeak):
        fit_two_stage(pairs, corpus, guard, cfg(), "logistic")


def test_an_unlabelled_pair_of_a_held_out_work_is_not_training_data():
    corpus, pairs, guard = synthetic(heldout=("W0000000003",))
    pairs.label[pairs.work == 3] = -1  # what build_pairs does for a held-out work
    check_trainable(pairs, corpus, guard, purpose="test")


@pytest.mark.parametrize("kind", ["logistic", "lightgbm"])
def test_learned_fusion_is_calibrated_deterministic_and_uses_the_hierarchy(kind):
    pytest.importorskip("sklearn")
    pytest.importorskip("lightgbm")
    corpus, pairs, guard = synthetic()
    c = cfg()
    m1, info = fit_two_stage(pairs, corpus, guard, c, kind)
    m2, _ = fit_two_stage(pairs, corpus, guard, c, kind)
    pa1, parent1, cal1 = m1.predict(pairs)
    _pa2, _parent2, cal2 = m2.predict(pairs)
    assert np.array_equal(cal1, cal2)  # a fixed seed gives the same model
    assert cal1.min() >= 0.0 and cal1.max() <= 1.0
    assert np.isnan(parent1[::2]).all() and not np.isnan(parent1[1::2]).any()  # roots have none
    grid = np.linspace(0, 1, 101)
    out = m1.calibrator.apply(grid)
    assert (np.diff(out) >= -1e-12).all() and out.min() >= 0 and out.max() <= 1  # monotonic
    assert info["n_calibration"] == int((pairs.kind == KIND_GOLD_RANDOM).sum()) - int(
        np.isnan(info["oof_b"][pairs.kind == KIND_GOLD_RANDOM]).sum()
    )
    # the signals carry the label, so the model must beat chance
    y = pairs.label == 1
    assert cal1[y].mean() > cal1[~y].mean() + 0.2
