"""Variant merging, phrase extraction and the scoring of mined phrases (P1-05)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from flatatlas.taxonomy import mine as tmine
from flatatlas.taxonomy.config import BackgroundConfig, MineConfig
from flatatlas.taxonomy.phrases import extract, key_of
from flatatlas.text.composite import CompositeParts


@pytest.mark.parametrize(
    "a, b",
    [
        ("ω-automata", "omega automata"),
        ("Ω-Automata", "omega automaton"),
        ("synchronising", "synchronizing"),
        ("Synchronisation of automata", "synchronization of automaton"),
        ("regular languages", "regular language"),
        ("Büchi automata", "buchi automaton"),
        ("context-free grammars", "context free grammar"),
        ("minimisation", "minimization"),
        ("analyse", "analyze"),
    ],
)
def test_variants_share_a_key(a, b):
    assert key_of(a) == key_of(b)


@pytest.mark.parametrize(
    "a, b",
    [("regular", "irregular"), ("precise", "prize"), ("series", "sery"), ("pushdown", "push down")],
)
def test_different_things_keep_different_keys(a, b):
    assert key_of(a) != key_of(b)


def test_extract_cuts_phrases_at_punctuation_stop_words_and_variables():
    found = extract("State complexity of deletion: a new approach to the shuffle of k words")
    assert "state complexity" in found
    assert "complexity of deletion" in found
    assert "state" in found
    # no phrase starts or ends with a stop or generic word, and none crosses the colon
    assert not any(k.startswith(("a ", "new ", "the ", "to ")) for k in found)
    assert "deletion a" not in found
    assert not any("approach" in k.split() for k in found)
    assert "shuffle" in found and "word" in found
    assert not any(" k " in f" {k} " for k in found)  # the variable k breaks a phrase


def test_extract_keeps_one_surface_per_key_and_is_deterministic():
    text = "Regular Languages and regular language operations"
    assert extract(text) == extract(text)
    assert extract(text)["regular language"] == "regular languages"  # first surface seen


def test_extract_ignores_numbers_and_math():
    found = extract("A 2-dimensional bound of n^2 states for k = 3")
    assert not any(any(ch.isdigit() for ch in k) for k in found)


# -- scoring --------------------------------------------------------------------------------------


def parts(work_id, title, *, refs=(), abstract="", year="2010"):
    return CompositeParts(
        work_id=work_id,
        title=title,
        venue="DLT",
        year=year,
        reference_titles=tuple(refs),
        abstract=abstract,
        tldr="",
        n_references=len(refs),
        n_references_with_title=len(refs),
        abstract_source="openalex" if abstract else None,
    )


CFG = MineConfig(min_docs=3, top_candidates=50)
BG = BackgroundConfig(exclude_title_words=["automata"])


def corpus():
    return [
        parts("W1", "Shuffle product of regular languages", year="2001"),
        parts("W2", "The shuffle of words and languages", year="1999"),
        parts("W3", "Shuffle operation on trace languages", year="2005"),
        parts("W4", "Shuffle product closure properties", year="2008"),
        parts("W5", "State complexity of union", abstract="We study the problem of union."),
        parts("W6", "State complexity of star"),
        parts("W7", "State complexity of reversal"),
        parts("W8", "Learning in the limit", refs=["Shuffle product basics"]),
    ]


BACKGROUND = [f"Graph colouring problems {i}" for i in range(20)] + [
    "A problem of learning in the limit",
    "Learning problems on graphs",
    "Complexity of problems",
]


def test_generic_tail_words_merge_shuffle_product_with_shuffle():
    rows = tmine.mine(corpus(), BACKGROUND, CFG, BG)
    by_key = {r["key"]: r for r in rows}
    assert "shuffle" in by_key
    assert "shuffle product" not in by_key  # folded into "shuffle"
    shuffle = by_key["shuffle"]
    assert "shuffle product" in shuffle["variants"] or "shuffle product" in shuffle["merged_from"]
    assert shuffle["df"] == 5  # W1-W4 and W8 (a reference title)
    assert shuffle["first_year"] == 1999


def test_references_alone_do_not_make_a_phrase_but_count_less_than_a_title():
    rows = tmine.mine(corpus(), BACKGROUND, CFG, BG)
    keys = {r["key"] for r in rows}
    assert "basic" not in keys  # only in one reference title
    stats = tmine.count_phrases(corpus(), CFG)
    assert stats["shuffle"].weights["W8"] == pytest.approx(CFG.reference_weight)
    assert stats["shuffle"].weights["W1"] == pytest.approx(CFG.title_weight)


def test_specific_phrases_outrank_common_ones_and_ranks_are_dense():
    rows = [r for r in tmine.mine(corpus(), BACKGROUND, CFG, BG) if r["source"] == "text"]
    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    by_key = {r["key"]: r for r in rows}
    assert by_key["shuffle"]["specificity"] > 0.99
    # "problem" is frequent in the background, so it cannot beat a phrase absent from it
    problem = by_key.get("problem")
    if problem is not None:
        assert problem["specificity"] < by_key["shuffle"]["specificity"]
        assert problem["rank"] > by_key["shuffle"]["rank"]


def test_mining_is_deterministic_and_independent_of_input_order():
    first = tmine.mine(corpus(), BACKGROUND, CFG, BG)
    again = tmine.mine(list(reversed(corpus())), list(reversed(BACKGROUND)), CFG, BG)
    assert first == again


def test_ctfidf_is_zero_for_unseen_and_grows_with_frequency():
    stats = tmine.count_phrases(corpus(), CFG)
    scores = tmine.ctfidf(stats, {}, n_flat=8, n_bg=10)
    assert scores["shuffle"] > scores["state complexity of union"] >= 0.0
    assert tmine.specificity(0.0, 0, 10, 10) == pytest.approx(0.5)  # no evidence either way
    assert tmine.specificity(5.0, 0, 10, 10) == pytest.approx(1.0)
    assert tmine.ranking_score(0.0, 1.0) == 0.0
    assert tmine.ranking_score(math.e - 1, 1.0) == pytest.approx(1.0)


def test_subphrase_pruning_keeps_the_longer_phrase_when_df_is_close():
    df = {"state complexity": 10, "state": 11, "complexity": 30}
    assert tmine.prune_subphrases(list(df), df) == {"state"}  # 10 >= 0.8 * 11; 30 is too far off


def test_keywords_are_listed_apart_and_never_merged():
    rows = tmine.mine(
        corpus(), BACKGROUND, CFG, BG, keywords={"Shuffle": 4, "Quantum": 6, "rare": 1}
    )
    kw = [r for r in rows if r["source"] == "openalex_keyword"]
    assert [r["key"] for r in kw] == ["quantum"]  # "rare" is below min_docs; "shuffle" matched text
    assert kw[0]["rank"] is None and kw[0]["openalex_keyword_works"] == 6
    shuffle = next(r for r in rows if r["key"] == "shuffle" and r["source"] == "text")
    assert shuffle["openalex_keyword_works"] == 4


def test_embedding_suggestions_come_from_work_vectors_only():
    rows = corpus()
    rng = np.random.default_rng(0)
    base = rng.normal(size=16)
    vectors = {p.work_id: base + rng.normal(scale=0.01, size=16) for p in rows}
    out = tmine.mine(rows, BACKGROUND, CFG, BG, vectors=vectors)
    suggested = [r for r in out if r["merge_suggestions"]]
    assert suggested, "all works share one direction, so some phrases must be suggested"
    for r in suggested:
        assert all(s["cosine"] >= CFG.merge_embedding_cosine for s in r["merge_suggestions"])
    plain = tmine.mine(rows, BACKGROUND, CFG, BG)
    assert {r["key"] for r in plain} == {r["key"] for r in out}  # suggestions never merge
