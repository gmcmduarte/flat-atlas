"""The composite text of a work (PLAN §9.3, P1-05): parts, selection of references, determinism."""

from __future__ import annotations

import random

from flatatlas.text.composite import (
    MAX_REFERENCES,
    Reference,
    WorkInputs,
    build_parts,
    choose_references,
    clean,
    compose,
)


def ref(i: int, *, title: str | None = "", in_corpus=False, cited=0) -> Reference:
    return Reference(f"W{i:04d}", f"Title {i}" if title == "" else title, in_corpus, cited)


def work(**kw) -> WorkInputs:
    base = dict(work_id="W1", title="State complexity of union", venue="DLT", year=2014)
    return WorkInputs(**{**base, **kw})


def test_full_text_has_every_part_in_the_fixed_order():
    w = work(
        references=(ref(1), ref(2)),
        abstract="We study union.",
        abstract_source="openalex",
        tldr="Union is hard.",
    )
    p = build_parts(w)
    assert p.text == (
        "State complexity of union · DLT · 2014 · References: Title 1; Title 2 · "
        "We study union. · TLDR: Union is hard."
    )
    assert (p.has_abstract, p.has_tldr, p.abstract_source) == (True, True, "openalex")
    assert (p.n_references, p.n_references_with_title) == (2, 2)


def test_without_abstract_tldr_or_references_the_parts_are_simply_missing():
    p = build_parts(work())
    assert p.text == "State complexity of union · DLT · 2014"
    assert not p.has_abstract and not p.has_tldr and p.abstract_source is None
    assert p.reference_titles == () and p.n_references == 0
    bare = build_parts(WorkInputs(work_id="W2", title="T"))
    assert bare.text == "T"


def test_more_than_ten_references_keep_ten_chosen_by_the_fixed_rule():
    refs = [ref(i, in_corpus=i % 7 == 0, cited=i % 5) for i in range(1, 40)]
    p = build_parts(work(references=refs))
    assert len(p.reference_titles) == MAX_REFERENCES == 10
    # in-corpus references come first (7, 14, 21, 28, 35), best cited first, ties by ID
    in_corpus = sorted(
        (r for r in refs if r.in_corpus), key=lambda r: (-r.n_citing_in_corpus, r.openalex_id)
    )
    assert list(p.reference_titles[:5]) == [r.title for r in in_corpus]
    assert p.n_references == 39


def test_reference_choice_ignores_input_order():
    refs = [ref(i, in_corpus=i % 3 == 0, cited=i % 4) for i in range(1, 30)]
    expected = choose_references(refs)
    for seed in range(5):
        shuffled = refs[:]
        random.Random(seed).shuffle(shuffled)
        assert choose_references(shuffled) == expected
        assert (
            build_parts(work(references=shuffled)).text == build_parts(work(references=refs)).text
        )


def test_references_without_a_title_are_counted_but_never_shown():
    refs = [ref(1), ref(2, title=None), ref(3, title="   "), ref(1)]  # a duplicate ID too
    titles, n_refs, n_titled = choose_references(refs)
    assert titles == ["Title 1"] and n_refs == 3 and n_titled == 1


def test_repeated_titles_appear_once():
    refs = [ref(1, title="Regular languages"), ref(2, title="regular  languages"), ref(3)]
    titles, _, _ = choose_references(refs)
    assert len(titles) == 2


def test_clean_removes_placeholders_and_collapses_space():
    assert clean("An [Formula: see text]-state  NFA\n") == "An -state NFA"
    assert clean(None) == "" and clean("   ") == ""


def test_compose_of_parts_is_the_text_property():
    p = build_parts(work(references=(ref(1),)))
    assert compose(p) == p.text
    assert build_parts(work(references=(ref(1),))).text == p.text  # same on every run
