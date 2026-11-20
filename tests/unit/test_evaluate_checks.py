"""The label-free checks on toys, the adoption rule, the one-time opening and the exit codes."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest
from tagging_helpers import cfg, corpus_of, dag_of, labels_of, part, topics_file
from typer.testing import CliRunner

from flatatlas.cli import app
from flatatlas.evaluate import checks, freeze, heldout, metrics, variants
from flatatlas.tagging.fusion import Selection

DAG = dag_of(topics_file())
RL = DAG.index["regular-languages"]
DFA = DAG.index["deterministic-finite-automata"]
CW = DAG.index["combinatorics-on-words"]


def sel(*rows, primary=None, low=False) -> Selection:
    rows = [(t, p, d) for t, p, d in rows]
    return Selection(rows, primary, low_confidence=low, untagged=not rows)


def test_coverage_counts_the_fallback_tag_separately() -> None:
    sels = {
        0: sel((RL, 0.9, False), primary=RL),
        1: sel((CW, 0.2, False), primary=CW, low=True),  # best level-0 topic, low confidence
        2: sel(),  # untagged
        3: sel((RL, 0.7, False), primary=RL),
    }
    c = checks.coverage(sels)
    assert c["strict"] == pytest.approx(0.5) and c["any"] == pytest.approx(0.75)


def test_stability_is_the_share_of_unchanged_primary_tags() -> None:
    a = {0: sel((RL, 0.9, False), primary=RL), 1: sel((CW, 0.9, False), primary=CW), 2: sel()}
    b = {0: sel((RL, 0.8, False), primary=RL), 1: sel((RL, 0.8, False), primary=RL), 2: sel()}
    s = checks.stability(a, b)
    assert s["unchanged"] == pytest.approx(0.5) and s["n"] == 2  # the untagged work is not counted


def test_venue_sanity_ranks_level_zero_topics_with_derived_rows() -> None:
    sels = {
        0: sel((DFA, 0.9, False), (RL, 0.9, True), primary=DFA),  # derived parent counts
        1: sel((RL, 0.8, False), primary=RL),
        2: sel((CW, 0.8, False), primary=CW),
    }
    v = checks.venue_sanity(
        sels,
        ["DLT", "DLT", "DLT"],
        {"DLT": ["regular-languages", "combinatorics-on-words"]},
        DAG,
        1,
    )
    assert v["detail"]["DLT:regular-languages"]["rank"] == 1
    assert v["detail"]["DLT:combinatorics-on-words"]["ok"] is False  # rank 2, only the top 1 counts
    assert v["rate"] == pytest.approx(0.5)
    assert (
        checks.venue_sanity(sels, ["DLT"] * 3, {"DLT": ["regular-languages"]}, DAG, 1)["rate"]
        == 1.0
    )


def test_citation_consistency_counts_references_that_share_a_level_zero_topic() -> None:
    sels = {
        0: sel((RL, 0.9, False), primary=RL),
        1: sel((DFA, 0.9, False), (RL, 0.9, True), primary=DFA),  # shares RL through the parent
        2: sel((CW, 0.9, False), primary=CW),
    }
    edges = [(0, 1, False), (0, 2, False)]
    assert checks.citation_consistency(sels, edges, DAG)["mean"] == pytest.approx(0.5)


def test_anchors_broken_on_purpose_fall_below_the_threshold() -> None:
    probs = {0: {RL: 0.9, CW: 0.1}, 1: {CW: 0.9, RL: 0.1}}
    good = [("a", "regular-languages", 0, "g"), ("b", "combinatorics-on-words", 1, "g")]
    assert checks.anchor_hits(good, probs, DAG)["groups"]["all"]["rate"] == 1.0
    broken = [("a", "combinatorics-on-words", 0, "g"), ("b", "regular-languages", 1, "g")]
    # top 3 of a work that has only two scored topics still contains both, so make them miss
    probs3 = {0: {RL: 0.9}, 1: {CW: 0.9}}
    res = checks.anchor_hits(broken, probs3, DAG)
    assert res["groups"]["all"]["rate"] == 0.0 and len(res["misses"]) == 2


def test_method_agreement_flags_topics_where_families_disagree() -> None:
    n = 4
    ev = lambda rows: np.array(rows, dtype=float)  # noqa: E731
    fam = {
        "l0": [RL, CW],
        "evidence": {
            "lexical": ev([[1, 0], [1, 0], [0, 1], [0, 1]]),
            "embedding": ev([[1, 0], [0, 1], [0, 1], [1, 0]]),
            "source": ev([[0, 0]] * n),  # no evidence: no pair with it
        },
    }
    out = checks.method_agreement(fam, DAG, 0.6)
    assert out["pairs"]["lexical-embedding"]["top1_agreement"] == pytest.approx(0.5)
    assert out["pairs"]["lexical-source"]["n_works"] == 0
    # regular-languages: lexical {0,1}, embedding {0,3}: Jaccard 1/3; combinatorics: {2,3} vs {1,2}
    assert out["per_topic"]["regular-languages"] == pytest.approx(1 / 3)
    assert set(out["flagged"]) == {"regular-languages", "combinatorics-on-words"}


def test_recovery_after_hiding_the_title_signal() -> None:
    before = {0: sel((RL, 0.9, False), primary=RL), 1: sel((CW, 0.9, False), primary=CW)}
    after = {0: sel((RL, 0.6, False), primary=RL), 1: sel((RL, 0.6, False), primary=RL)}
    r = checks.recovery(before, after, [0, 1], DAG)
    assert r["tags_recovered"] == 0.5 and r["primary_unchanged"] == 0.5


# -- the adoption rule ------------------------------------------------------------------------


def fake_checks(anchors=0.95, coverage=0.95, stability=0.97, venue=1.0, hard=None) -> dict:
    h = hard or {
        "anchors": anchors >= 0.9,
        "coverage": coverage >= 0.85,
        "stability": stability >= 0.95,
        "venue_sanity": venue >= 1.0,
    }
    return {
        "anchors": {"rate": anchors, "hit": 1, "n": 1},
        "coverage": {"strict": coverage, "any": coverage},
        "stability": {"unchanged": stability},
        "venue_sanity": {"rate": venue, "met": 1, "total": 1},
        "hard": h,
    }


def fake_frozen(**per_key) -> dict:
    return {
        "run_id": "t",
        "variants": {k: {"checks": per_key.get(k, fake_checks())} for k in variants.KEYS},
    }


def diffs(**kw) -> dict:
    """Paired differences: ``kw[key] = (value, lo, hi)`` for the ladder keys, 0 elsewhere."""
    out = {}
    for key in variants.LADDER:
        v, lo, hi = kw.get(key, (0.0, -0.05, 0.05))
        e = metrics.Estimate(v, lo, hi)
        out[key] = {"mean_f": e}
    return out


def test_a_complex_method_needs_an_interval_that_excludes_zero() -> None:
    d = heldout.decide(fake_frozen(), diffs(fusion=(0.08, 0.04, 0.12)))
    assert d["adopted"] == "fusion" and not d["decision_model"] and not d["propagation"]
    d = heldout.decide(
        fake_frozen(), diffs(fusion=(0.08, -0.01, 0.12))
    )  # point estimate up, zero inside
    assert d["adopted"] == "noisy_or"


def test_the_decision_model_is_considered_only_after_fusion_is_adopted() -> None:
    both = diffs(fusion=(0.08, 0.04, 0.12), **{"fusion+dm": (0.01, 0.0005, 0.02)})
    assert heldout.decide(fake_frozen(), both)["adopted"] == "fusion+dm"
    only_dm = diffs(**{"fusion+dm": (0.05, 0.02, 0.08)})
    assert heldout.decide(fake_frozen(), only_dm)["adopted"] == "noisy_or"  # fusion not adopted


def test_a_significantly_worse_difference_is_never_adopted() -> None:
    d = heldout.decide(fake_frozen(), diffs(fusion=(-0.08, -0.12, -0.04)))
    assert d["adopted"] == "noisy_or"


def test_a_hard_check_that_the_simpler_method_passes_and_this_one_fails_blocks_adoption() -> None:
    frozen = fake_frozen(**{"fusion": fake_checks(anchors=0.80)})  # simpler neighbour: 0.95, passes
    d = heldout.decide(frozen, diffs(fusion=(0.08, 0.04, 0.12)))
    assert d["rungs"]["fusion"]["hard"]["anchors"]["worse"] and d["adopted"] == "noisy_or"


def test_a_drop_that_stays_above_the_threshold_is_shown_but_does_not_block() -> None:
    # anchors 0.92 against 0.99: lower, both pass the 0.90 threshold. Stability 1.0 against 0.96
    # likewise. Read the other way, nothing could beat a noisy-or whose stability is exactly 1.
    frozen = fake_frozen(
        **{
            "noisy_or": fake_checks(anchors=0.99, stability=1.0),
            "fusion": fake_checks(anchors=0.92, stability=0.96),
        }
    )
    d = heldout.decide(frozen, diffs(fusion=(0.08, 0.04, 0.12)))
    hard = d["rungs"]["fusion"]["hard"]
    assert hard["anchors"]["complex"] < hard["anchors"]["simple"] and not hard["any_worse"]
    assert d["adopted"] == "fusion"


def test_propagation_is_adopted_for_the_chosen_method_only() -> None:
    d = heldout.decide(
        fake_frozen(), diffs(fusion=(0.08, 0.04, 0.12), **{"fusion+prop": (0.02, 0.005, 0.03)})
    )
    assert d["adopted"] == "fusion+prop" and d["propagation"]
    other = heldout.decide(fake_frozen(), diffs(**{"fusion+prop": (0.02, 0.005, 0.03)}))
    assert other["adopted"] == "noisy_or"  # fusion not adopted; fusion+prop is not considered


# -- the opening ------------------------------------------------------------------------------


def toy_world(tmp_path, *, leak=False):
    parts = [part(f"W{i:010d}", f"title {i}") for i in range(6)]
    corpus = corpus_of(parts)
    entries = [(parts[i].work_id, ["regular-languages"], "train", "random") for i in range(4)]
    entries += [(parts[i].work_id, ["regular-languages"], "heldout", "random") for i in (4, 5)]
    labels = labels_of(entries)
    ctx = SimpleNamespace(corpus=corpus, dag=DAG)
    probs = {r: {RL: 0.9, CW: 0.1} for r in range(6)}
    reports = tmp_path / "reports"
    reports.mkdir(parents=True)
    gold, topics = tmp_path / "gold.yaml", tmp_path / "topics.yaml"
    gold.write_text("gold", encoding="utf-8")
    topics.write_text("topics", encoding="utf-8")
    c = cfg()
    vdict = {}
    for key in variants.KEYS:
        f = reports / f"{key}.probs.parquet"
        sha = variants.save_probs(ctx, probs, f)
        vdict[key] = {
            "selection": {"threshold": 0.5, "max_topics": 3},
            "probs_file": str(f),
            "probs_sha256": sha,
            "checks": fake_checks(),
        }
    frozen = {
        "run_id": "t",
        "tuning_hash": freeze.tuning_hash(c),
        "gold_sha256": freeze.sha256_file(gold),
        "topics_sha256": freeze.sha256_file(topics),
        "fit_sets": {
            "training_works": [parts[i].work_id for i in range(4)]
            + ([parts[4].work_id] if leak else []),
            "seed_works": [],
        },
        "variants": vdict,
    }
    return corpus, labels, c, frozen, reports, gold, topics


def open_it(world, **kw):
    corpus, labels, c, frozen, reports, gold, topics = world
    return heldout.open_heldout(
        frozen, c, corpus, DAG, labels, reports, gold_path=gold, topics_path=topics, **kw
    )


def test_the_opening_scores_every_variant_and_locks(tmp_path) -> None:
    world = toy_world(tmp_path)
    res = open_it(world)
    assert res["n_works"] == 2 and not res["optimistic"]
    for key in variants.KEYS:
        assert res["estimates"][key]["f0"][0] == pytest.approx(1.0)  # both held-out works are RL
    assert heldout.lock_path(world[4]).exists()


def test_a_second_opening_is_refused_unless_it_says_it_is_optimistic(tmp_path) -> None:
    world = toy_world(tmp_path)
    open_it(world)
    with pytest.raises(heldout.HeldoutRefused, match="opened on"):
        open_it(world)
    again = open_it(world, again=True)
    assert again["optimistic"]


def test_the_opening_refuses_when_a_held_out_work_is_in_a_training_or_seed_set(tmp_path) -> None:
    world = toy_world(tmp_path, leak=True)
    with pytest.raises(heldout.HeldoutRefused, match="training_works"):
        open_it(world)
    assert not heldout.lock_path(world[4]).exists()  # a refusal does not use up the opening
    clean = toy_world(tmp_path / "b")
    clean[3]["fit_sets"]["seed_works"] = ["W0000000005"]  # a held-out work as a seed
    with pytest.raises(heldout.HeldoutRefused, match="seed_works"):
        open_it(clean)


def test_the_opening_refuses_when_the_settings_or_files_changed_after_the_freeze(tmp_path) -> None:
    world = toy_world(tmp_path)
    corpus, labels, c, frozen, reports, gold, topics = world
    gold.write_text("edited", encoding="utf-8")
    with pytest.raises(heldout.HeldoutRefused, match="gold.yaml"):
        open_it(world)
    gold.write_text("gold", encoding="utf-8")
    changed = c.model_copy(deep=True)
    changed.selection.threshold = 0.9
    with pytest.raises(heldout.HeldoutRefused, match="tagger.yaml"):
        heldout.open_heldout(
            frozen, changed, corpus, DAG, labels, reports, gold_path=gold, topics_path=topics
        )
    # the three adoption switches may change after the freeze
    switched = c.model_copy(deep=True)
    switched.decision_model.enabled = not switched.decision_model.enabled
    switched.propagation.enabled = True
    switched.method = "noisy_or"
    heldout.verify(frozen, switched, {"W0000000004"}, gold_path=gold, topics_path=topics)


def test_a_changed_probabilities_file_is_refused(tmp_path) -> None:
    world = toy_world(tmp_path)
    path = world[3]["variants"]["fusion"]["probs_file"]
    with open(path, "ab") as f:
        f.write(b"x")
    with pytest.raises(heldout.HeldoutRefused, match="fusion"):
        open_it(world)


# -- the exit code ---------------------------------------------------------------------------


def run_check(tmp_path, monkeypatch, frozen) -> int:
    monkeypatch.setenv("FLATATLAS_DATA_ROOT", str(tmp_path / "data"))
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps(frozen), encoding="utf-8")
    result = CliRunner().invoke(app, ["evaluate", "check", "--frozen", str(path), "--no-record"])
    return result.exit_code


def test_the_check_command_exits_non_zero_when_anchors_are_broken(tmp_path, monkeypatch) -> None:
    c = cfg()
    adopted = variants.key_of(c.method, c.decision_model.enabled, c.propagation.enabled)
    ok = fake_frozen()
    assert run_check(tmp_path, monkeypatch, ok) == 0
    broken = fake_frozen(**{adopted: fake_checks(anchors=0.5)})
    assert run_check(tmp_path, monkeypatch, broken) == 1
    # a variant that is not adopted may fail without failing the run
    other = "noisy_or" if adopted != "noisy_or" else "fusion"
    assert run_check(tmp_path, monkeypatch, fake_frozen(**{other: fake_checks(coverage=0.1)})) == 0
