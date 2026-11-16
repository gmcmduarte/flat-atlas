"""Schema and rules of ``taxonomy check`` for topics and the labelled set (P1-05)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from flatatlas.taxonomy import check as tcheck
from flatatlas.taxonomy.schema import split_for, topic_levels

FIXTURES = Path(__file__).parent.parent / "fixtures" / "taxonomy"


def valid_topics() -> dict:
    return yaml.safe_load((FIXTURES / "topics_valid.yaml").read_text(encoding="utf-8"))


def topics_from(data: dict):
    return tcheck.parse_topics(yaml.safe_dump(data))


def problems_of(data: dict, **kwargs) -> list[str]:
    return tcheck.check_topics(topics_from(data), **kwargs)


def entry(data: dict, topic_id: str) -> dict:
    return next(t for t in data["topics"] if t["id"] == topic_id)


# -- topics ---------------------------------------------------------------------------------------


def test_valid_file_passes_and_levels_are_shortest_distance_to_a_root():
    file = topics_from(valid_topics())
    assert tcheck.check_topics(file) == []
    levels = topic_levels(file.topics)
    assert levels == {
        "regular-languages": 0,
        "context-free-languages": 0,
        "descriptional-complexity": 1,
        "shuffle-of-words": 1,
        "unary-languages": 2,
    }


def test_the_real_taxonomy_files_in_the_repo_load_when_present():
    for path, loader in (
        (tcheck.TOPICS_FILE, tcheck.load_topics),
        (tcheck.GOLD_FILE, tcheck.load_gold),
    ):
        if path.exists():
            loader(path)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d["topics"].append(copy.deepcopy(d["topics"][0])), "duplicate topic id"),
        (lambda d: entry(d, "unary-languages").update(parents=["nope"]), "does not exist"),
        (
            lambda d: entry(d, "regular-languages").update(parents=["unary-languages"]),
            "cycle in the topic graph",
        ),
        (
            lambda d: entry(d, "context-free-languages").update(aliases=["rational languages"]),
            "is used by both",
        ),
        (
            lambda d: entry(d, "context-free-languages").update(aliases=["Regular  Languages"]),
            "is the name of topic",
        ),
        (
            lambda d: entry(d, "descriptional-complexity").update(
                exclude_phrases=["State-Complexity"]
            ),
            "both included and excluded",
        ),
    ],
)
def test_each_topic_rule_rejects_its_breakage(mutate, message):
    data = valid_topics()
    mutate(data)
    assert any(message in p for p in problems_of(data)), problems_of(data)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: entry(d, "regular-languages").update(id="Not A Slug"),
        lambda d: entry(d, "regular-languages").update(parents=["regular-languages"]),
        lambda d: entry(d, "regular-languages").update(origin="guess"),
        lambda d: entry(d, "regular-languages")["xref"].update(msc=["68Q4"]),
        lambda d: entry(d, "regular-languages").update(surprise=1),
        lambda d: d.update(taxonomy_version=0),
    ],
)
def test_schema_errors_are_reported_not_raised_as_tracebacks(mutate):
    data = valid_topics()
    mutate(data)
    with pytest.raises(tcheck.TaxonomyFileError):
        topics_from(data)


def test_siblings_may_not_share_a_phrase_without_a_context_word():
    data = valid_topics()
    # shuffle-of-words and descriptional-complexity are both children of regular-languages
    entry(data, "shuffle-of-words")["include_phrases"].append("State complexity")
    problems = problems_of(data)
    assert any("'state complexity' is shared by" in p and "without context" in p for p in problems)


def test_siblings_may_share_a_phrase_when_every_use_has_a_context_word():
    # "size" appears in both with a context, in the valid fixture
    assert problems_of(valid_topics()) == []


def test_two_roots_count_as_siblings():
    data = valid_topics()
    entry(data, "context-free-languages")["include_phrases"].append("regular language")
    assert any("roots" in p for p in problems_of(data))


def test_a_topic_below_a_deprecated_parent_is_reported():
    data = valid_topics()
    entry(data, "descriptional-complexity")["status"] = "deprecated"
    assert any("is deprecated" in p for p in problems_of(data))


def test_reviewed_topics_cannot_change_against_head_unless_allowed():
    head = topics_from(valid_topics())
    data = valid_topics()
    entry(data, "regular-languages")["name"] = "Regular sets"
    assert any("reviewed topic changed (name)" in p for p in problems_of(data, head=head))
    assert problems_of(data, head=head, allow_reviewed_edits=True) == []
    # an unreviewed topic can change freely
    data = valid_topics()
    entry(data, "unary-languages")["name"] = "Unary"
    assert problems_of(data, head=head) == []
    # and removing a reviewed topic counts as a change
    data = valid_topics()
    data["topics"] = [t for t in data["topics"] if t["id"] != "regular-languages"]
    for t in data["topics"]:
        t["parents"] = [p for p in t["parents"] if p != "regular-languages"]
    assert any("was removed" in p for p in problems_of(data, head=head))


def test_phrases_compare_after_folding():
    from flatatlas.taxonomy.schema import normalise_phrase

    assert normalise_phrase("ω-Automata") == normalise_phrase("ω automata")
    assert normalise_phrase("Büchi  automata") == "buchi automata"


# -- labelled set ---------------------------------------------------------------------------------


def work_ids(n: int, want: str) -> list[str]:
    out = []
    i = 0
    while len(out) < n:
        wid = f"W{i:010d}".replace("0", "A").replace("1", "B")
        i += 1
        if split_for(wid) == want:
            out.append(wid)
    return out


def valid_gold() -> dict:
    train = work_ids(2, "train")
    held = work_ids(1, "heldout")
    return {
        "taxonomy_version": 1,
        "works": [
            {"work": train[0], "labels": ["regular-languages"], "split": "train", "reviewed": True},
            {
                "work": train[1],
                "labels": ["regular-languages", "descriptional-complexity"],
                "split": "train",
                "sampling": "topup",
            },
            {"work": held[0], "labels": ["context-free-languages"], "split": "heldout"},
        ],
    }


def gold_problems(data: dict, *, known: set[str] | None = None, **kwargs) -> list[str]:
    ids = known if known is not None else {w["work"] for w in data["works"]}
    return tcheck.check_gold(
        tcheck.parse_gold(yaml.safe_dump(data)),
        topics_from(valid_topics()),
        resolve_work=lambda w: w if w in ids else None,
        **kwargs,
    )


def test_a_valid_gold_file_passes():
    assert gold_problems(valid_gold()) == []


def test_split_is_a_stable_function_of_the_work_id_with_about_a_third_held_out():
    ids = [f"W{i:010d}" for i in range(3000)]
    share = sum(split_for(i) == "heldout" for i in ids) / len(ids)
    assert 0.30 < share < 0.37
    # pinned: changing the rule would silently move labelled works between train and held-out
    assert {
        w: split_for(w) for w in ("WT3SYS5P77T", "WAAAAAAAAAA", "WBBBBBBBBBB", "WCCCCCCCCCC")
    } == {
        "WT3SYS5P77T": "train",
        "WAAAAAAAAAA": "heldout",
        "WBBBBBBBBBB": "train",
        "WCCCCCCCCCC": "heldout",
    }


def test_gold_rule_split_must_equal_the_hash_rule():
    data = valid_gold()
    data["works"][0]["split"] = "heldout"
    assert any("hash rule gives" in p for p in gold_problems(data))


def test_gold_rule_topup_works_are_never_heldout():
    data = valid_gold()
    held = data["works"][2]
    held["sampling"] = "topup"
    assert any("top-up work cannot be held out" in p for p in gold_problems(data))


def test_gold_rule_every_work_resolves_to_a_surviving_id():
    data = valid_gold()
    first = data["works"][0]["work"]
    assert any("not a known work ID" in p for p in gold_problems(data, known=set()))
    resolver = tcheck.check_gold(
        tcheck.parse_gold(yaml.safe_dump(data)),
        topics_from(valid_topics()),
        resolve_work=lambda w: "WZZZZZZZZZZ" if w == first else w,
    )
    assert any("was merged into WZZZZZZZZZZ" in p for p in resolver)


def test_gold_rule_labels_exist_and_are_level_0_or_1():
    data = valid_gold()
    data["works"][0]["labels"] = ["nope"]
    assert any("is not a topic" in p for p in gold_problems(data))
    data = valid_gold()
    data["works"][0]["labels"] = ["unary-languages"]  # level 2
    assert any("deeper than level 1" in p for p in gold_problems(data))


def test_gold_rule_taxonomy_version_matches_topics():
    data = valid_gold()
    data["taxonomy_version"] = 2
    assert any("taxonomy_version is 2" in p for p in gold_problems(data))


def test_gold_rule_duplicates_and_bad_ids():
    data = valid_gold()
    data["works"].append(copy.deepcopy(data["works"][0]))
    assert any("listed twice" in p for p in gold_problems(data))
    data = valid_gold()
    data["works"][0]["work"] = "not-an-id"
    with pytest.raises(tcheck.TaxonomyFileError):
        tcheck.parse_gold(yaml.safe_dump(data))


def test_gold_reviewed_entries_are_protected_against_head():
    head = tcheck.parse_gold(yaml.safe_dump(valid_gold()))
    data = valid_gold()
    data["works"][0]["labels"] = ["context-free-languages"]
    assert any("reviewed label changed" in p for p in gold_problems(data, head=head))
    assert gold_problems(data, head=head, allow_reviewed_edits=True) == []
    data = valid_gold()
    data["works"][1]["labels"] = ["regular-languages"]  # not reviewed: free to change
    assert gold_problems(data, head=head) == []
    data = valid_gold()
    del data["works"][0]
    assert any("reviewed label removed" in p for p in gold_problems(data, head=head))


def test_the_checked_in_fixture_gold_file_pair_is_accepted_and_broken_ones_rejected():
    gold = tcheck.parse_gold((FIXTURES / "gold_valid.yaml").read_text(encoding="utf-8"))
    topics = tcheck.parse_topics((FIXTURES / "topics_valid.yaml").read_text(encoding="utf-8"))
    ids = {w.work for w in gold.works}
    assert tcheck.check_gold(gold, topics, resolve_work=lambda w: w if w in ids else None) == []
    for broken in sorted(FIXTURES.glob("gold_broken_*.yaml")):
        g = tcheck.parse_gold(broken.read_text(encoding="utf-8"))
        ids = {w.work for w in g.works} - {"WMISSINGAAA"}
        found = tcheck.check_gold(
            g, topics, resolve_work=lambda w, ids=ids: w if w in ids else None
        )
        assert found, f"{broken.name} should be rejected"
