"""The HTML report renders from a frozen record and held-out numbers, and stays self-contained."""

from __future__ import annotations

import re

from test_evaluate_checks import fake_frozen

from flatatlas.evaluate import report, variants


def est(v):
    return [v, v - 0.05, v + 0.05]


def full_frozen() -> dict:
    f = fake_frozen()
    for v in f["variants"].values():
        c = v["checks"]
        c["venue_sanity"]["detail"] = {
            "DLT:regular-languages": {"rank": 1, "share": 0.3, "ok": True}
        }
        c["citation_consistency"] = {"mean": 0.8, "n_works": 10}
        c["coherence"] = {"baseline_cosine": 0.3, "topics": {}}
    for k in ("noisy_or", "fusion"):
        f["variants"][k]["checks"]["leak_test"] = {
            "tags_recovered": 0.5,
            "primary_unchanged": 0.6,
            "n_works": 20,
            "n_tags": 30,
        }
    f["method_agreement"] = {
        "pairs": {"lexical-embedding": {"top1_agreement": 0.5, "n_works": 100}},
        "per_topic": {},
        "flagged": ["machine-models"],
    }
    return f


def full_heldout(optimistic=False) -> dict:
    metrics = ["p0", "r0", "f0", "p1", "r1", "f1", "mf0", "mf1", "mean_f"]
    rungs = {
        k: {
            "against": s,
            "diff": 0.01,
            "lo": -0.02,
            "hi": 0.04,
            "excludes_zero": False,
            "better": True,
            "hard": {
                "anchors": {"complex": 0.9, "simple": 0.95, "worse": False},
                "any_worse": False,
            },
            "adopt": False,
        }
        for k, s in variants.LADDER.items()
    }
    return {
        "optimistic": optimistic,
        "n_works": 159,
        "bootstrap": {"n": 2000, "seed": 1, "interval": 0.9},
        "n_gold_labels": {"level0": 250, "level1": 260},
        "estimates": {k: {m: est(0.7) for m in metrics} for k in variants.KEYS},
        "differences": {"topdown vs fusion": {"mean_f": est(-0.2)}},
        "decision": {"rungs": rungs, "adopted": "noisy_or"},
        "calibration": {
            k: [{"lo": 0, "hi": 0.1, "n": 10, "stated": 0.05, "observed": 0.1}]
            for k in variants.KEYS
        },
        "by_type": {"abstract": {"abstract": {"n": 5, **{k: 0.7 for k in variants.KEYS}}}},
    }


TOPICS = [
    {"id": "regular-languages", "level": 0, "n": 50, "mean_conf": 0.8, "agreement": 0.3,
     "npmi": 0.1, "cosine": 0.4, "flag": False},
    {"id": "machine-models", "level": 0, "n": 20, "mean_conf": 0.6, "agreement": 0.1,
     "npmi": None, "cosine": float("nan"), "flag": True},
]  # fmt: skip


def test_the_report_has_every_section_and_no_outside_resource() -> None:
    link = report.link(report.WorkLink("A <title> & more", 2001, "10.1/x", "conf/x/Y01"))
    spot = {"regular-languages": {"10 random": [link], "10 lowest confidence": []}}
    page = report.render(
        full_frozen(), full_heldout(), TOPICS, spot, adopted="noisy_or", notes=["a note"]
    )
    for text in (
        "Summary: the hard checks",
        "Held-out set (159 works",
        "adoption rule",
        "Calibration",
        "By paper type",
        "Method agreement",
        "Hold-out leak test",
        "regular-languages",
        "https://doi.org/10.1/x",
        "https://dblp.org/rec/conf/x/Y01",
        "A &lt;title&gt; &amp; more",
        "a note",
    ):
        assert text in page, text
    assert "Optimistic" not in page
    # self-contained: no external script, stylesheet, image or font
    assert not re.search(r"<(script|link|img)[^>]+(src|href)=['\"]https?://", page)
    assert page.count("<table class='sortable'") == 1


def test_an_optimistic_opening_is_labelled_and_a_draft_has_no_held_out_table() -> None:
    page = report.render(full_frozen(), full_heldout(optimistic=True), TOPICS, {}, adopted="fusion")
    assert "Optimistic" in page
    draft = report.render(full_frozen(), None, TOPICS, {}, adopted="fusion")
    assert "has not been opened yet" in draft and "Held-out set (" not in draft


def test_a_failed_hard_check_is_marked() -> None:
    f = full_frozen()
    c = f["variants"]["fusion"]["checks"]
    c["stability"]["unchanged"] = 0.9
    c["hard"]["stability"] = False
    page = report.render(f, None, TOPICS, {}, adopted="fusion")
    assert "FAIL" in page
