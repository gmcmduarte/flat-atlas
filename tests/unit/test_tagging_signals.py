"""Matching, lexical signals, artefacts and the shortlist (P1-07, PLAN §9.2, §9.3)."""

from __future__ import annotations

import numpy as np
import pytest
from tagging_helpers import (
    build,
    cfg,
    corpus_of,
    dag_of,
    desc_space,
    labels_of,
    part,
    small_parts,
    topics_file,
)

from flatatlas.tagging import artefacts as art_mod
from flatatlas.tagging import noisyor, shortlist
from flatatlas.tagging.guard import Guard
from flatatlas.tagging.matcher import Matcher, PhraseEntry, tokenise
from flatatlas.tagging.signals import compute_signals, lexical_row, percentile, work_features


def dictionary():
    file = topics_file()
    dag = dag_of(file)
    include, exclude = art_mod.build_dictionary(file, dag, cfg(), [])
    return dag, include, exclude


def lex(title, **kw):
    dag, include, exclude = dictionary()
    title_s, abs_s, refs_s = lexical_row(include, exclude, part("W1", title, **kw), 1.5)
    named = lambda d: None if d is None else {dag.ids[t]: v for t, v in d.items()}  # noqa: E731
    return named(title_s), named(abs_s), named(refs_s)


# -- matching -------------------------------------------------------------------------------------


def test_tokens_fold_case_hyphens_spelling_and_plurals():
    assert tokenise("Finite-State Automata") == tokenise("finite state automaton")
    assert tokenise("Minimisation of Automata")[0] == tokenise("minimization")[0]
    assert tokenise("ω-regular languages")[:2] == ["omega", "regular"]


def test_a_phrase_matches_on_word_boundaries_only():
    m = Matcher([PhraseEntry(0, tuple(tokenise("dfa")), 1.0)])
    assert m.find(tokenise("A DFA for words"), None)
    assert m.find(tokenise("Two DFAs"), None)  # plural
    assert not m.find(tokenise("Medfaring"), None)


def test_hyphen_and_spelling_variants_hit_the_same_phrase():
    t, _a, _r = lex("Regular-Language Theory")  # hyphen and singular
    assert t["regular-languages"] == pytest.approx(1.0)
    t, _a, _r = lex("Deterministic Finite-Automata in practice")
    assert "deterministic-finite-automata" in t


def test_alias_matches_and_a_longer_phrase_does_not_double_count():
    t, _a, _r = lex("Minimal DFA construction")
    assert t["deterministic-finite-automata"] > 0
    t, _a, _r = lex("Deterministic finite automata")
    assert t["deterministic-finite-automata"] == pytest.approx(1.0)
    assert t["regular-languages"] == pytest.approx(1.0)  # "finite automata" inside it


def test_ambiguous_phrase_needs_a_context_word():
    t, _a, _r = lex("A minimal model of cities")
    assert "regular-languages" not in t
    t, _a, _r = lex("Minimal automaton construction")
    assert "regular-languages" in t


def test_exclude_phrase_vetoes_the_topic_in_that_field():
    t, _a, _r = lex("Pushdown automata versus finite automata")
    assert "regular-languages" not in t
    t, a, _r = lex("Finite automata", abstract="We study pushdown finite automata at length.")
    assert t["regular-languages"] > 0  # the veto is per field
    assert a is not None and "regular-languages" not in a


def test_work_without_abstract_or_references_has_missing_signals_not_zeros():
    t, a, r = lex("Finite automata")
    assert t["regular-languages"] > 0
    assert a is None and r is None


def test_abstract_signal_grows_with_the_number_of_matches():
    _t, a1, _r = lex(
        "x", abstract="finite automata are studied here in many different settings now"
    )
    _t, a2, _r = lex(
        "x", abstract="finite automata and regular languages: finite automata for regular languages"
    )
    assert a2["regular-languages"] > a1["regular-languages"] > 0


def test_reference_signal_is_the_weighted_share_of_matching_reference_titles():
    _t, _a, r = lex("x", refs=["Finite automata", "Graph colouring", "Regular languages", "Trees"])
    assert r["regular-languages"] == pytest.approx(0.5)


def test_reference_title_exclude_phrase_vetoes_only_that_reference():
    _t, _a, r = lex("x", refs=["Pushdown finite automata", "Finite automata"])
    assert r["regular-languages"] == pytest.approx(0.5)


# -- percentiles and signals ----------------------------------------------------------------------


def test_percentile_is_the_share_of_reference_scores_at_or_below():
    ref = np.array([0.1, 0.2, 0.3, 0.4])
    assert percentile(ref, np.array([0.0, 0.25, 0.4, 0.9])).tolist() == [0.0, 0.5, 1.0, 1.0]
    assert np.isnan(percentile(np.zeros(0), np.array([0.5]))[0])


def test_held_out_works_are_never_seeds_centroids_or_reference_scores():
    parts = small_parts()
    ids = [p.work_id for p in parts]
    entries = [
        (ids[0], ["regular-languages"], "heldout", "random"),
        (ids[1], ["regular-languages"], "train", "random"),
        (ids[2], ["regular-languages"], "train", "topup"),
    ]
    _f, dag, corpus, labels, art = build(parts, entries)
    held = corpus.index[ids[0]]
    topup = corpus.index[ids[2]]
    for rows in art.seeds:
        assert held not in rows
    for c in art.centroids:
        if c is not None:
            assert held not in c.members
    assert held not in set(art.reference_rows) and topup not in set(art.reference_rows)
    assert ids[1] != ""  # the train work is allowed


def test_seed_works_from_the_topics_file_drop_held_out_ones_and_report_them():
    parts = small_parts()
    ids = [p.work_id for p in parts]
    file = topics_file()
    file.topics[1].seed_works = [ids[0], ids[1]]
    dag = dag_of(file)
    corpus = corpus_of(parts)
    labels = labels_of([(ids[0], ["regular-languages"], "heldout", "random")])
    art = art_mod.build_artefacts(file, dag, corpus, labels, cfg(), [], desc_space(dag.n), key="t")
    assert art.seeds_dropped == {"deterministic-finite-automata": [ids[0]]}
    assert corpus.index[ids[0]] not in art.seeds[1]


def test_a_seed_member_is_scored_without_itself():
    parts = small_parts()
    _f, dag, corpus, labels, art = build(parts, [])
    t = dag.index["deterministic-finite-automata"]
    c = art.centroids[t]
    assert c is not None and c.members
    member = next(iter(c.members))
    rows = np.array([member])
    left_out = c.scores(corpus.vectors[rows], rows)[0]
    plain = c.scores(corpus.vectors[rows])[0]
    assert left_out < plain  # without itself the centroid is farther from it


def test_signals_have_the_expected_shapes_and_missing_values():
    parts = small_parts()
    _f, dag, corpus, labels, art = build(parts, [])
    sig = compute_signals(art, corpus, dag, labels, cfg())
    for name, m in sig.matrices.items():
        assert m.shape == (len(parts), dag.n), name
    assert np.isnan(sig.matrices["lex_abstract"]).all()  # no abstracts in this corpus
    assert np.isnan(sig.matrices["lex_refs"]).all()
    assert not np.isnan(sig.matrices["lex_title"]).any()
    assert sig.matrices["lex_title"][0, dag.index["deterministic-finite-automata"]] == 1.0
    pct = sig.matrices["emb_seed"]
    assert np.nanmin(pct) >= 0 and np.nanmax(pct) <= 1
    feats = work_features(parts, corpus.emb_source)
    assert feats["has_abstract"].sum() == 0 and feats["n_references"].sum() == 0


def test_source_signal_uses_the_mapped_openalex_topic_score():
    parts = small_parts()
    openalex = [{} for _ in parts]
    openalex[3] = {"T1": 0.8}
    file = topics_file()
    dag = dag_of(file)
    corpus = corpus_of(parts, openalex=openalex)
    labels = labels_of([])
    art = art_mod.build_artefacts(file, dag, corpus, labels, cfg(), [], desc_space(dag.n), key="t")
    sig = compute_signals(art, corpus, dag, labels, cfg())
    col = sig.matrices["src_openalex"][:, dag.index["regular-languages"]]
    assert col[3] == pytest.approx(0.8)
    assert np.isnan(col[0])  # a work without OpenAlex topics: absent
    assert np.isnan(sig.matrices["src_openalex"][:, dag.index["avoidability"]]).all()  # no mapping


# -- shortlist -----------------------------------------------------------------------------------


def test_shortlist_has_ancestors_and_reports_recall():
    parts = small_parts()
    entries = [
        (
            parts[0].work_id,
            ["regular-languages", "deterministic-finite-automata"],
            "train",
            "random",
        )
    ]
    _f, dag, corpus, labels, art = build(parts, entries)
    sig = compute_signals(art, corpus, dag, labels, cfg())
    pn = noisyor.noisy_or(sig.matrices, cfg())
    cand = shortlist.shortlist(sig, pn, cfg())
    closed = shortlist.with_ancestors(cand, dag)
    child = dag.index["deterministic-finite-automata"]
    parent = dag.index["regular-languages"]
    assert cand[0, child] and closed[0, parent]
    assert (closed >= cand).all()
    r = shortlist.recall(closed, corpus.index, dag, labels, [parts[0].work_id])
    assert r["all"] == 1.0 and r["misses"] == []
    # a label no topic list reaches is reported as a miss
    cand[:] = False
    closed = shortlist.with_ancestors(cand, dag)
    r = shortlist.recall(closed, corpus.index, dag, labels, [parts[0].work_id])
    assert r["all"] == 0.0 and len(r["misses"]) == 2


def test_guard_filters_and_refuses_held_out_works():
    labels = labels_of([("W0000000001", ["regular-languages"], "heldout", "random")])
    guard = Guard(labels.gold)
    assert guard.drop(["W0000000001", "W0000000002"]) == (["W0000000002"], ["W0000000001"])
    with pytest.raises(Exception, match="held-out"):
        guard.check(["W0000000001"], purpose="test")
    guard.check(["W0000000002"], purpose="test")
