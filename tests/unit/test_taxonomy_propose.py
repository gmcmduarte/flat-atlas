"""``taxonomy propose``: parent evidence, soft links, synonyms and determinism (P1-05)."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pytest

from flatatlas.taxonomy import cluster as tcluster
from flatatlas.taxonomy import propose as tp
from flatatlas.taxonomy.check import check_topics
from flatatlas.taxonomy.config import ProposeConfig
from flatatlas.taxonomy.mine import PhraseStats
from flatatlas.text.composite import CompositeParts

CFG = ProposeConfig(min_topic_size=3, max_topics=50)


def cand(cid: str, works: Iterable[int], *, name: str | None = None, score: float = 5.0, **kw):
    return tp.Candidate(
        cid=cid, name=name or cid, origin="mined", works=frozenset(works), score=score, **kw
    )


def inputs_for(cands: list[tp.Candidate], **kw) -> tp.Inputs:
    return tp.Inputs(
        parts=[], phrase_rows=[], stats={}, clusters=kw.pop("clusters", []), members=[], **kw
    )


def links_between(cands, *, covering=None, **kw):
    inputs = inputs_for(cands, **kw)
    work_ids = [f"W{i}" for i in range(max(max(c.works) for c in cands) + 1)]
    return tp.find_links(cands, inputs, work_ids, covering or {}, CFG)


# -- evidence kinds -------------------------------------------------------------------------------


def test_subsumption_on_a_synthetic_co_assignment_matrix():
    parent = cand("regular", range(0, 40))
    child = cand("unary", range(0, 8))  # P(parent|child) = 1.0, P(child|parent) = 0.2
    sibling = cand("shuffle", range(30, 45))  # only partly inside the parent
    unrelated = cand("grids", range(100, 110))
    links = links_between([parent, child, sibling, unrelated])
    assert [lk["parent"] for lk in links["unary"]] == ["regular"]
    link = links["unary"][0]
    assert link["evidence"] == {"subsumption": tp.W_SUBSUMPTION}
    assert link["p_parent_given_child"] == 1.0 and link["p_child_given_parent"] == 0.2
    assert "shuffle" not in links  # P(parent|child) = 10/15 is below 0.7
    assert "grids" not in links and "regular" not in links


def test_equal_sized_topics_are_not_parents_of_each_other():
    a, b = cand("a", range(10)), cand("b", range(10))
    assert links_between([a, b]) == {}


def test_a_child_that_covers_most_of_the_parent_is_not_subsumed():
    # P(parent|child) = 1 but P(child|parent) = 0.9: the two are near-synonyms, not parent/child
    parent = cand("p", range(0, 20))
    child = cand("c", range(0, 18))
    assert links_between([parent, child]) == {}


def test_head_word_alone_is_not_enough_but_head_plus_nesting_is():
    parent = cand("pushdown automata", range(0, 40), name="pushdown automata")
    child = cand(
        "deterministic pushdown automata", range(30, 50), name="deterministic pushdown automata"
    )
    # 10 of 20 child works inside the parent: no subsumption, only the head word (1.0)
    assert links_between([parent, child]) == {}
    parent.cluster_matches = [{"cluster": "g70-c1", "jaccard": 0.9}]
    child.cluster_matches = [{"cluster": "g12-c5", "jaccard": 0.9}]
    clusters = [
        {"cluster_id": "g70-c1", "parent_cluster": None},
        {"cluster_id": "g12-c5", "parent_cluster": "g70-c1"},
    ]
    links = links_between([parent, child], clusters=clusters, covering={"g70-c1": parent.cid})
    lk = links[child.cid][0]
    assert lk["evidence"] == {"head": tp.W_HEAD_SUFFIX, "nested-clusters": tp.W_NESTED}
    assert lk["score"] == 2.0


def test_head_word_inside_counts_half():
    child = cand("a", range(5), name="state complexity of union")
    parent = cand("b", range(9), name="state complexity")
    assert tp._head_points(child, parent) == tp.W_HEAD_INSIDE
    assert (
        tp._head_points(cand("c", [1], name="regular union"), cand("d", [1, 2], name="union"))
        == tp.W_HEAD_SUFFIX
    )
    assert tp._head_points(parent, child) == 0.0  # a longer phrase is never the head of a shorter


def test_citation_evidence_needs_edges_share_and_direction():
    parent = cand("p", range(0, 30), name="alpha")
    child = cand("c", range(0, 6), name="beta")  # inside the parent: subsumption (2.0) as well
    work_ids = [f"W{i}" for i in range(30)]
    cites = [(f"W{i}", f"W{20 + i}") for i in range(4)]  # child works cite parent-only works
    inputs = inputs_for([parent, child], citations=cites)
    links = tp.find_links([parent, child], inputs, work_ids, {}, CFG)
    assert links["c"][0]["evidence"]["citation"] == tp.W_CITATION
    back = tp.find_links(
        [parent, child],
        inputs_for([parent, child], citations=[(b, a) for a, b in cites]),
        work_ids,
        {},
        CFG,
    )
    assert "citation" not in back["c"][0]["evidence"]


def test_ccs_structure_is_evidence():
    parent = cand("p", range(0, 30), name="alpha")
    child = cand("c", range(25, 40), name="beta")
    parent.seed_matches = [{"scheme": "ccs", "id": "100", "label": "x", "jaccard": 1.0}]
    child.seed_matches = [{"scheme": "ccs", "id": "101", "label": "y", "jaccard": 1.0}]
    seeds = [
        {"scheme": "ccs", "id": "100", "label": "x", "parents": []},
        {"scheme": "ccs", "id": "101", "label": "y", "parents": ["100"]},
    ]
    assert links_between([parent, child], seeds=seeds) == {}  # 1.5 < min_link_score 2.0
    child.name = "alpha beta"  # plus a head word (1.0)
    links = links_between([parent, child], seeds=seeds)
    assert set(links["c"][0]["evidence"]) == {"seed-structure", "head"}


# -- reduction, soft links ------------------------------------------------------------------------


def test_transitive_reduction_keeps_the_nearest_parent_and_limits_parents():
    big, mid, small = (
        cand("big", range(0, 60)),
        cand("mid", range(0, 25)),
        cand("small", range(0, 8)),
    )
    links = links_between([big, mid, small])
    assert {lk["parent"] for lk in links["small"]} == {"big", "mid"}
    kept = tp.reduce_links(links, [big, mid, small], CFG)
    assert [lk["parent"] for lk in kept["small"]] == ["mid"]  # big is an ancestor of mid
    assert [lk["parent"] for lk in kept["mid"]] == ["big"]


def test_soft_links_never_chain():
    a = cand("a", range(0, 100))
    b = cand("b", range(0, 50))  # 50% inside a, P(child|parent) high: no scored link
    c = cand("c", range(0, 20))
    accepted: dict = {}
    n = tp.soft_attach([a, b, c], accepted, ProposeConfig(soft_attach_containment=0.4))
    assert accepted["b"][0]["parent"] == "a" and accepted["b"][0]["soft"] is True
    assert accepted["c"][0]["parent"] == "a"  # not "b": b's own parent is soft
    assert "a" not in accepted and n == 2


# -- end to end on a small corpus -----------------------------------------------------------------


def make_part(i: int, title: str, venue="DLT", year="2010") -> CompositeParts:
    return CompositeParts(
        work_id=f"W{i:03d}", title=title, venue=venue, year=year, reference_titles=(),
        abstract="", tldr="", n_references=0, n_references_with_title=0, abstract_source=None,
    )  # fmt: skip


def small_inputs() -> tp.Inputs:
    titles = (
        [f"Regular languages and automata number {i}" for i in range(12)]
        + [f"Unary regular languages {i}" for i in range(5)]
        + [f"Shuffle of regular languages {i}" for i in range(4)]
        + [f"Pushdown automata study {i}" for i in range(6)]
    )
    parts = [make_part(i, t) for i, t in enumerate(titles)]
    stats: dict[str, PhraseStats] = {}

    def add(key: str, surface: str, work_idx: Iterable[int]):
        s = PhraseStats(key)
        for i in work_idx:
            s.add(f"W{i:03d}", 1.0, part="title", year=2010, surface=surface)
        stats[key] = s

    add("regular language", "regular languages", range(0, 21))
    add("unary regular language", "unary regular languages", range(12, 17))
    add("shuffle", "shuffle", range(17, 21))
    add("pushdown automaton", "pushdown automata", range(21, 27))
    rows = []
    for rank, (key, s) in enumerate(sorted(stats.items(), key=lambda kv: -len(kv[1].weights)), 1):
        rows.append(
            {"rank": rank, "key": key, "phrase": s.surface, "source": "text",
             "n_tokens": len(key.split()), "score": 10.0 - rank, "specificity": 1.0,
             "variants": [s.surface], "merge_suggestions": []}
        )  # fmt: skip
    return tp.Inputs(parts=parts, phrase_rows=rows, stats=stats, clusters=[], members=[])


def test_propose_builds_a_valid_proposal_with_parents_and_aliases():
    result = tp.propose(small_inputs(), CFG)
    assert result.problems == []
    by_name = {t.name: t for t in result.file.topics}
    assert set(by_name) == {
        "Regular languages",
        "Unary regular languages",
        "Shuffle",
        "Pushdown automata",
    }
    reg = by_name["Regular languages"]
    assert reg.parents == [] and reg.status == "proposed" and reg.reviewed is False
    assert by_name["Unary regular languages"].parents == [reg.id]
    assert by_name["Shuffle"].parents == [reg.id]  # 4 of 4 works inside, scored by subsumption
    assert by_name["Pushdown automata"].parents == []  # no work in common
    assert check_topics(result.file) == []
    assert result.stats["roots"] == 2


def test_propose_is_deterministic():
    a = tp.propose(small_inputs(), CFG)
    b = tp.propose(small_inputs(), CFG)
    assert a.file.model_dump() == b.file.model_dump()
    # and independent of the order phrase rows arrive in
    shuffled = small_inputs()
    shuffled.phrase_rows = list(reversed(shuffled.phrase_rows))
    assert tp.propose(shuffled, CFG).file.model_dump() == a.file.model_dump()


def test_synonyms_on_the_same_works_become_one_topic_with_an_alias():
    inputs = small_inputs()
    s = PhraseStats("rl")
    for i in range(0, 21):
        s.add(f"W{i:03d}", 1.0, part="title", year=2010, surface="rational languages")
    inputs.stats["rl"] = s
    inputs.phrase_rows.append(
        {"rank": 9, "key": "rl", "phrase": "rational languages", "source": "text", "n_tokens": 2,
         "score": 0.5, "specificity": 1.0, "variants": ["rational languages"],
         "merge_suggestions": []}
    )  # fmt: skip
    result = tp.propose(inputs, CFG)
    regular = next(t for t in result.file.topics if t.name == "Regular languages")
    assert "rational languages" in regular.aliases and len(result.file.topics) == 4


def test_unigram_must_be_nearly_absent_from_the_background():
    inputs = small_inputs()
    for r in inputs.phrase_rows:
        if r["key"] == "shuffle":
            r["specificity"] = 0.95
    names = {t.name for t in tp.propose(inputs, CFG).file.topics}
    assert "Shuffle" not in names


def test_max_topics_keeps_the_best_scored():
    result = tp.propose(small_inputs(), ProposeConfig(min_topic_size=3, max_topics=2))
    assert len(result.file.topics) == 2


@pytest.mark.parametrize("n", [1, 5])
def test_phrases_are_owned_by_one_topic(n):
    result = tp.propose(small_inputs(), CFG)
    seen: dict[str, str] = {}
    for t in result.file.topics:
        for p in t.include_phrases:
            assert seen.setdefault(str(p), t.id) == t.id


# -- cluster helpers ------------------------------------------------------------------------------


def test_cluster_labels_use_c_tf_idf_and_skip_contained_terms():
    ids = [f"W{i}" for i in range(6)]
    assignment = np.array([0, 0, 0, 1, 1, 1])
    pw = {
        "shuffle": {"W0": 1, "W1": 1, "W2": 1},
        "shuffle product": {"W0": 1, "W1": 1},
        "automaton": {f"W{i}": 1 for i in range(6)},
        "quantum": {"W3": 1, "W4": 1},
    }
    labels = tcluster.label_clusters(assignment, ids, pw, 3)
    assert labels[0][0][0] == "shuffle"
    assert all(k != "shuffle product" for k, _ in labels[0])  # contained in "shuffle"
    assert labels[1][0][0] == "quantum"
    assert labels[0][0][0] != "automaton"  # in every cluster, so no cluster is named by it


def test_nesting_needs_a_majority_inside_one_coarse_cluster():
    coarse = np.array([0, 0, 0, 0, 1, 1, -1, -1])
    fine = np.array([0, 0, 1, 1, 2, 2, 3, 3])
    parents = tcluster.nest(coarse, fine, 70, 12)
    assert parents["g12-c0"] == ("g70-c0", 1.0)
    assert parents["g12-c2"] == ("g70-c1", 1.0)
    assert "g12-c3" not in parents  # only noise above it
    mixed = tcluster.nest(np.array([0, 0, 1, 1]), np.array([0, 0, 0, 0]), 70, 12)
    assert "g12-c0" not in mixed  # 50% < 60%


def test_seed_overlap_is_lexical_and_reports_the_scheme():
    seeds = [
        {"scheme": "msc", "id": "68R15", "label": "Combinatorics on words: repetitions, patterns"},
        {"scheme": "msc", "id": "68Q80", "label": "Cellular automata"},
    ]
    hits = tcluster.seed_overlap(["combinatorics", "word", "repetition"], seeds)
    assert [h["id"] for h in hits] == ["68R15"]
    assert tcluster.seed_overlap([], seeds) == []


def test_excluded_phrases_participles_and_adverbs_are_not_topics():
    inputs = small_inputs()
    for key, surface in (
        ("accepted", "accepted"),
        ("whether", "whether"),
        ("finitely", "finitely"),
    ):
        s = PhraseStats(key)
        for i in range(0, 8):
            s.add(f"W{i:03d}", 1.0, part="title", year=2010, surface=surface)
        inputs.stats[key] = s
        inputs.phrase_rows.append(
            {"rank": 20, "key": key, "phrase": surface, "source": "text", "n_tokens": 1,
             "score": 1.0, "specificity": 1.0, "variants": [surface], "merge_suggestions": []}
        )  # fmt: skip
    cfg = ProposeConfig(min_topic_size=3, max_topics=50, exclude_phrases=["Whether"])
    names = {t.name.lower() for t in tp.propose(inputs, cfg).file.topics}
    assert names.isdisjoint({"accepted", "whether", "finitely"})
    assert "pushdown automata" in names
