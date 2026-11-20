"""The local decision model: prompts, options, selection, cache, resume, calibration (P1-07b).

Nothing here loads a real model: a ``FakeScorer`` or a tiny scripted scorer answers.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import duckdb
import numpy as np
import pytest
from tagging_helpers import cfg, dag_of, topics_file

from flatatlas.tagging.config import DecisionModelConfig
from flatatlas.tagging.decide import questions as q
from flatatlas.tagging.decide.cache import (
    DecisionCache,
    ModelInfo,
    WorkAnswers,
    make_key,
)
from flatatlas.tagging.decide.features import I_CHILD, I_L0, attach
from flatatlas.tagging.decide.run import WorkTask, level0, run_decisions
from flatatlas.tagging.decide.scorer import FakeScorer, LlamaScorer, MissingLlmExtra
from flatatlas.tagging.decide.select import band_hits, child_questions, disagreement_rows
from flatatlas.tagging.pairs import FEATURES, Pairs

INFO = ModelInfo("fake.gguf", "0" * 64, "none", "fake", q.PROMPT_VERSION)


def dag():
    return dag_of(topics_file())


def topics6():
    return [
        q.Topic(f"t{i}", f"Topic {i}", f"Topic {i} is about thing {i}. More text.")
        for i in range(6)
    ]


# -- prompts ----------------------------------------------------------------------------------


def test_prompts_are_stable_text():
    t = topics6()
    a = q.choice_prompt("Paper one", t, (0, 1, 2, 3, 4, 5))
    assert a == q.choice_prompt("Paper one", t, (0, 1, 2, 3, 4, 5))
    assert "A. Topic 0: Topic 0 is about thing 0." in a  # a one-line description
    assert "More text" not in a
    assert a.endswith("<think>\n\n</think>\n\n")  # thinking is off, the answer comes first


def test_the_shared_part_comes_first():
    t = topics6()
    order = (2, 0, 1, 5, 4, 3)
    a = q.choice_prompt("Paper one", t, order)
    b = q.choice_prompt("A different paper", t, order)
    shared = q.chatml("").split("<|im_end|>")[0]  # the system turn
    prefix = q.choice_prefix(t, order)
    assert a.startswith(shared) and prefix in a and prefix in b
    assert a.index(prefix) < a.index("Paper one")  # options before the paper
    # yes/no: instructions and the paper first, then the topic
    ya, yb = q.yesno_prompt("Paper one", t[0]), q.yesno_prompt("Paper one", t[1])
    common = 0
    for x, y in zip(ya, yb, strict=False):
        if x != y:
            break
        common += 1
    assert "Paper one" in ya[:common]
    assert "thing 0" not in ya[:common] and "thing 0" in ya[common:]


def test_prompt_version_is_part_of_the_cache_key():
    k1 = make_key("W1", "l0", 0, "sha", "dm-1")
    k2 = make_key("W1", "l0", 0, "sha", "dm-2")
    assert k1 != k2 and make_key("W1", "l0", 0, "sha2", "dm-1") != k1


def test_option_orders_are_fixed_distinct_permutations():
    orders = q.option_orders(21, 3)
    assert orders == q.option_orders(21, 3)
    assert all(sorted(o) == list(range(21)) for o in orders)
    assert len(set(orders)) == 3
    assert orders[0] == tuple(range(21)) and orders[1] == tuple(reversed(range(21)))
    with pytest.raises(ValueError):
        q.option_orders(21, 4)


def test_one_line_cuts_at_the_first_sentence():
    assert q.one_line("First one. Second one.") == "First one."
    long = "word " * 80
    assert len(q.one_line(long)) <= 201 and q.one_line(long).endswith("…")


# -- order effects ----------------------------------------------------------------------------


class Biased:
    """Truly prefers one topic (by name) but also likes the first position."""

    def __init__(self, truth: str, bias: float):
        self.truth, self.bias, self.calls = truth, bias, 0

    def score(self, prompt, options):
        self.calls += 1
        listing = dict(re.findall(r"^([A-Z])\. ([^:]+):", prompt, flags=re.M))
        logits = np.array([2.0 if listing.get(o) == self.truth else 0.0 for o in options])
        logits[0] += self.bias
        e = np.exp(logits - logits.max())
        return e / e.sum()


def test_averaging_over_orders_corrects_a_scorer_biased_to_the_first_option():
    t = topics6()
    scorer = Biased("Topic 3", bias=3.0)
    per_order = []
    for order in q.option_orders(6, 3):
        probs = scorer.score(q.choice_prompt("p", t, order), q.choice_options(6))
        per_order.append(q.by_topic(order, probs))
    assert int(np.argmax(per_order[0])) == 0  # one order follows the bias
    avg = q.average(per_order)
    assert int(np.argmax(avg)) == 3  # the average finds the real preference
    assert avg.sum() == pytest.approx(1.0)


# -- selection --------------------------------------------------------------------------------


def test_band_hits_looks_at_levels_zero_and_one_only():
    d = dag()
    t = d.index
    by_work = {
        0: {t["regular-languages"]: 0.4},
        1: {t["regular-languages"]: 0.9, t["deterministic-finite-automata"]: 0.45},
        2: {t["regular-languages"]: 0.1},
        3: {t["regular-languages"]: 0.9},
    }
    assert band_hits(by_work, d, (0.3, 0.5)) == {0, 1}
    assert band_hits(by_work, d, (0.35, 0.45)) == {0, 1}
    assert band_hits(by_work, d, (0.46, 0.5)) == set()


def test_disagreement_between_families_on_the_level_zero_topic():
    d = dag()
    t = d.index
    n = 3
    from flatatlas.tagging.config import SIGNALS

    m = {name: np.full((n, d.n), np.nan, dtype=np.float32) for name in SIGNALS}
    for name in m:
        m[name][:] = 0.0
    m["lex_title"][0, t["regular-languages"]] = 1.0  # lexical: regular
    m["src_openalex"][0, t["combinatorics-on-words"]] = 1.0  # source: words -> disagree
    m["lex_title"][1, t["regular-languages"]] = 1.0
    m["src_openalex"][1, t["regular-languages"]] = 1.0  # both agree
    m["lex_title"][2, t["regular-languages"]] = 1.0  # only one family speaks
    assert disagreement_rows(m, d, cfg()) == {0}


def test_child_questions_are_capped_and_ordered():
    d = dag()
    t = d.index
    l0 = {t["regular-languages"]: 0.8, t["combinatorics-on-words"]: 0.2}
    asked = child_questions(l0, {}, set(), d, top_l0=1, max_level=1, cap=10)
    assert asked == [t["deterministic-finite-automata"]]  # only children of the top topic
    asked = child_questions(l0, {}, {t["avoidability"]}, d, top_l0=1, max_level=1, cap=10)
    assert asked == [t["deterministic-finite-automata"], t["avoidability"]]  # + shortlisted
    asked = child_questions(l0, {}, {t["avoidability"]}, d, top_l0=2, max_level=1, cap=1)
    assert len(asked) == 1


# -- the run: cache, resume, cap ----------------------------------------------------------------


def tasks():
    d = dag()
    t = d.index
    out = []
    for i in range(4):
        out.append(
            WorkTask(
                f"W{i:010d}",
                f"Deterministic automata paper number {i}",
                {t["regular-languages"]: 0.4},
                {t["deterministic-finite-automata"], t["avoidability"]},
            )
        )
    return out


def dm_cfg(**kw):
    return DecisionModelConfig(flush_every=2, **kw)


def run(scorer, cache, **kw):
    return run_decisions(
        tasks(), dag=dag(), scorer=scorer, cache=cache, info=INFO, cfg=dm_cfg(**kw)
    )


def test_a_cache_hit_makes_no_model_call():
    cache = DecisionCache()
    first = FakeScorer()
    r1 = run(first, cache, option_orders=2)
    assert first.calls and r1.l0_asked == 8 and r1.child_asked > 0
    second = FakeScorer()
    r2 = run(second, cache, option_orders=2)
    assert second.calls == []  # not one model call
    assert r2.asked == 0 and r2.l0_cached == 8
    for w, res in r1.results.items():
        assert r2.results[w].l0 == pytest.approx(res.l0)
        assert r2.results[w].child == pytest.approx(res.child)


def test_a_changed_prompt_is_a_miss_even_with_the_same_key():
    cache = DecisionCache()
    key = make_key("W1", "l0", 0, INFO.sha256, INFO.prompt_version)
    cache.put(key, "hash-a", [0.5, 0.5], INFO)
    assert cache.get(key, "hash-a") == [0.5, 0.5]
    assert cache.get(key, "hash-b") is None


class Dies(FakeScorer):
    def __init__(self, after: int):
        super().__init__()
        self.after = after

    def score(self, prompt, options):
        if len(self.calls) >= self.after:
            raise KeyboardInterrupt
        return super().score(prompt, options)


def test_a_run_resumes_after_an_interruption_through_the_saved_cache(tmp_path):
    con = duckdb.connect()
    path = tmp_path / "local_decision.parquet"
    cache = DecisionCache()
    dying = Dies(after=7)
    saved = {"n": 0}

    def flush():
        cache.save(con, path)
        saved["n"] += 1

    with pytest.raises(KeyboardInterrupt):
        run_decisions(
            tasks(), dag=dag(), scorer=dying, cache=cache, info=INFO,
            cfg=dm_cfg(option_orders=2), flush=flush,
        )  # fmt: skip
    assert len(dying.calls) == 7 and saved["n"] >= 1
    reloaded = DecisionCache.load(con)
    n_saved = len(reloaded)
    assert 0 < n_saved <= 7  # what was flushed survives
    again = FakeScorer()
    done = run(again, reloaded, option_orders=2)
    fresh = FakeScorer()
    run(fresh, DecisionCache(), option_orders=2)
    assert len(again.calls) == len(fresh.calls) - n_saved  # only what was missing is asked
    assert done.results.keys() == {t.work_id for t in tasks()}


def test_the_number_of_yes_no_questions_per_work_is_capped():
    cache = DecisionCache()
    r = run(FakeScorer(), cache, option_orders=1, max_child_questions=1)
    assert r.child_asked == len(tasks())  # one per work
    assert all(len(res.child) == 1 for res in r.results.values())


def test_one_option_order_asks_one_choice_question_per_work():
    r = run(FakeScorer(), DecisionCache(), option_orders=1)
    assert r.l0_asked == len(tasks())
    assert all(
        res.l0 is not None and res.l0.sum() == pytest.approx(1.0) for res in r.results.values()
    )


def test_the_cache_round_trips_through_the_warehouse(tmp_path):
    con = duckdb.connect()
    cache = DecisionCache()
    run(FakeScorer(), cache, option_orders=2)
    cache.save(con, tmp_path / "x.parquet")
    back = DecisionCache.load(con)
    assert back.rows.keys() == cache.rows.keys()
    d = dag()
    a = back.answers(
        INFO.sha256, INFO.prompt_version, n_orders=2, l0_topics=level0(d), topic_index=d.index
    )
    assert set(a) == {t.work_id for t in tasks()}
    assert all(wa.l0 is not None for wa in a.values())
    # a work with only one of two orders cached has no level-0 answer
    one = back.answers(
        INFO.sha256, INFO.prompt_version, n_orders=3, l0_topics=level0(d), topic_index=d.index
    )
    assert all(wa.l0 is None for wa in one.values())


# -- features -----------------------------------------------------------------------------------


def test_attach_fills_only_active_works_and_takes_the_branch_value_for_children():
    d = dag()
    t = d.index
    rows = [0, 0, 1, 1]
    topics = [t["regular-languages"], t["deterministic-finite-automata"]] * 2
    X = np.full((4, len(FEATURES)), np.nan, dtype=np.float32)
    pairs = Pairs(
        np.array(rows), np.array(topics), np.ones(4, bool), X, np.zeros(4),
        -np.ones(4, dtype=np.int8), np.zeros(4, dtype=np.int8), [[] for _ in range(4)],
    )  # fmt: skip
    wa = WorkAnswers(
        l0={t["regular-languages"]: 0.7, t["combinatorics-on-words"]: 0.3},
        child={t["deterministic-finite-automata"]: 0.9},
    )
    answers = {"W0": wa, "W1": wa}
    counts = attach(pairs, d, ["W0", "W1"], answers, active={"W0"})
    assert pairs.X[0, I_L0] == pytest.approx(0.7) and np.isnan(pairs.X[0, I_CHILD])
    assert pairs.X[1, I_L0] == pytest.approx(0.7)  # the branch value
    assert pairs.X[1, I_CHILD] == pytest.approx(0.9)
    assert np.isnan(pairs.X[2:, [I_L0, I_CHILD]]).all()  # W1 is not active: never a dm value
    assert counts["works"] == 1


# -- calibration and the guard ------------------------------------------------------------------


def test_calibrators_are_monotone_and_keep_nan():
    pytest.importorskip("sklearn")
    from flatatlas.tagging.decide.calibrate import fit_dm_calibrators
    from flatatlas.tagging.pairs import KIND_GOLD_RANDOM

    rng = np.random.default_rng(0)
    n = 400
    X = np.full((n, len(FEATURES)), np.nan, dtype=np.float32)
    level = (np.arange(n) % 2).astype(np.float32)
    X[:, FEATURES.index("t_level")] = level
    raw = rng.random(n).astype(np.float32)
    y = (rng.random(n) < raw).astype(np.int8)  # truth tracks the raw probability
    X[level == 0, I_L0] = raw[level == 0]
    X[level == 1, I_CHILD] = raw[level == 1]
    pairs = Pairs(
        np.arange(n), np.zeros(n, dtype=int), np.ones(n, bool), X, np.zeros(n), y,
        np.full(n, KIND_GOLD_RANDOM, dtype=np.int8), [[] for _ in range(n)],
    )  # fmt: skip
    cal = fit_dm_calibrators(pairs)
    assert cal.l0 is not None and cal.child is not None
    grid = np.linspace(0, 1, 50)
    for c in (cal.l0, cal.child):
        out = c.apply(grid)
        assert (np.diff(out) >= -1e-12).all() and out.min() >= 0 and out.max() <= 1
    applied = cal.apply(X)
    assert np.isnan(applied[level == 1, I_L0]).all()  # NaN stays NaN


def test_the_fit_with_the_decision_model_refuses_a_held_out_work():
    pytest.importorskip("sklearn")
    from test_tagging_fusion import synthetic

    from flatatlas.tagging.fusion import fit_two_stage
    from flatatlas.tagging.guard import HeldOutLeak

    corpus, pairs, guard = synthetic(heldout=("W0000000003",))
    with pytest.raises(HeldOutLeak):
        fit_two_stage(pairs, corpus, guard, cfg(), "logistic", use_dm=True)


def test_the_base_model_ignores_the_decision_columns():
    pytest.importorskip("sklearn")
    from test_tagging_fusion import synthetic

    from flatatlas.tagging.fusion import fit_two_stage
    from flatatlas.tagging.pairs import DM_FEATURES, N_BASE, PROP_FEATURES

    corpus, pairs, guard = synthetic()
    base, _ = fit_two_stage(pairs, corpus, guard, cfg(), "logistic")
    assert base.matrix(pairs).shape[1] == N_BASE and not base.use_dm
    dm_cols = [FEATURES.index(n) for n in DM_FEATURES]
    pairs.X[:, dm_cols] = np.random.default_rng(1).random((len(pairs), 2))  # dm columns change
    again, _ = fit_two_stage(pairs, corpus, guard, cfg(), "logistic")
    assert base.predict(pairs)[2] == pytest.approx(again.predict(pairs)[2])
    with_dm, info = fit_two_stage(pairs, corpus, guard, cfg(), "logistic", use_dm=True)
    assert with_dm.use_dm and with_dm.matrix(pairs).shape[1] == N_BASE + len(DM_FEATURES)
    # the pass-2 columns are read only by a model fitted with use_prop
    pairs.X[:, [FEATURES.index(n) for n in PROP_FEATURES]] = 0.3
    with_prop, _ = fit_two_stage(pairs, corpus, guard, cfg(), "logistic", use_prop=True)
    assert with_prop.use_prop and with_prop.matrix(pairs).shape[1] == N_BASE + len(PROP_FEATURES)
    assert base.predict(pairs)[2] == pytest.approx(again.predict(pairs)[2])
    assert info["n_dm_l0"] >= 0


# -- no hosted model, no model in the tests -----------------------------------------------------

FORBIDDEN = {"httpx", "requests", "urllib", "urllib3", "http", "aiohttp", "socket", "openai",
             "anthropic", "azure", "huggingface_hub", "websockets"}  # fmt: skip


def test_the_decide_package_cannot_reach_a_hosted_model():
    folder = Path(__file__).resolve().parents[2] / "src" / "flatatlas" / "tagging" / "decide"
    for path in sorted(folder.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in FORBIDDEN, f"{path.name} imports {name}"
        text = path.read_text(encoding="utf-8")
        assert "from_pretrained" not in text and "api_key" not in text.lower()


def test_the_local_scorer_needs_the_extra_or_the_file(tmp_path):
    with pytest.raises(MissingLlmExtra):
        LlamaScorer(tmp_path / "nothing.gguf")
