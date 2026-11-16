"""Rules of the resolve stage on small synthetic inputs (PLAN §8)."""

from __future__ import annotations

import pytest

from flatatlas.resolve.authors import (
    ExternalAuthor,
    align_authors,
    build_author_rows,
    group_external_authors,
    institution_of,
    map_external_authors,
)
from flatatlas.resolve.citations import build_citation_rows
from flatatlas.resolve.config import (
    AuthorsConfig,
    ResolveConfigError,
    SourceMatchConfig,
    parse_resolve_config,
)
from flatatlas.resolve.match import match_crossref, match_openalex, match_s2
from flatatlas.resolve.merge import (
    VersionRef,
    candidate_pairs,
    group_versions,
    primary_version,
    score_pair,
)
from flatatlas.resolve.text import (
    jaccard,
    name_similarity,
    normalise_doi,
    numbering_differs,
    page_count,
    same_surname,
    strip_markers,
    title_similarity,
)
from resolve_inputs import config

CFG = config().versions
MARKERS = CFG.strip_title_markers


# -- text -------------------------------------------------------------------------------------


def test_doi_case_and_prefix_do_not_matter() -> None:
    assert normalise_doi("https://doi.org/10.1007/ABC-1") == normalise_doi("10.1007/abc-1")
    assert normalise_doi("DOI:10.1007/ABC-1") == "10.1007/abc-1"
    assert normalise_doi("  ") is None and normalise_doi(None) is None


def test_markers_are_removed_from_titles_only_where_they_are_markers() -> None:
    assert strip_markers("Foo (Extended Abstract)", MARKERS) == "Foo"
    assert strip_markers("Foo: Full Version.", MARKERS) == "Foo"
    assert (
        strip_markers("Extended abstract models of Foo", MARKERS)
        == "Extended abstract models of Foo"
    )
    assert title_similarity("Foo Bar (Extended Abstract)", "foo  bar", MARKERS) == 1.0


def test_a_longer_title_is_not_a_match_for_a_contained_one() -> None:
    # The token-set ratio would say 1.0 here; the token-sort ratio does not.
    assert (
        title_similarity("Isometric Words", "Hypercubes and Isometric Words Based on Distance")
        < 0.6
    )


def test_part_numbers_distinguish_titles() -> None:
    assert numbering_differs("Pumping Words I", "Pumping Words II")
    assert numbering_differs("Foo, Part 1", "Foo, Part 2")
    assert not numbering_differs("Foo", "Foo (Extended Abstract)")


@pytest.mark.parametrize(
    ("dblp", "other", "expected"),
    [
        ("Karel Culík II", "Karel Čulík", True),
        ("Lila Kari", "Lila Kari A", True),
        ("M. Sakthi Balan", "Sakthi Balan Muthiah", True),
        ("Thomas Buchholz", "Buchholz, Thomas", True),
        ("Lane A. Hemaspaandra", "Piotr Faliszewski", False),
    ],
)
def test_surname_containment(dblp: str, other: str, expected: bool) -> None:
    assert same_surname(dblp, other) is expected


def test_name_similarity_and_helpers() -> None:
    assert name_similarity("Zeki O. Bayram", "Zeki Bayram") >= 0.9
    assert name_similarity("J. Smith", "John Smith") >= 0.9
    assert name_similarity("John Smith", "Jane Smith") < 0.85
    assert jaccard("ab", "bc") == pytest.approx(1 / 3)
    assert page_count("177-188") == 12 and page_count("e12") is None


# -- config -----------------------------------------------------------------------------------


def test_weights_must_sum_to_one() -> None:
    bad = {
        "versions": {
            "merge_min": 0.85,
            "report_min": 0.5,
            "weights": {"title": 0.5, "authors": 0.5, "embedding": 0.5, "extra": 0.5},
        }
    }
    with pytest.raises(ResolveConfigError, match="sum to 1"):
        parse_resolve_config(bad)


def test_the_real_config_file_loads() -> None:
    from flatatlas.resolve.config import load_resolve_config

    cfg = load_resolve_config()
    assert cfg.versions.merge_min == 0.85 and cfg.versions.report_min == 0.5


# -- §8.1 source matching ---------------------------------------------------------------------

SM = SourceMatchConfig()
PAPER = {
    "dblp_key": "conf/c/X",
    "title": "Fast Regular Expression Matching",
    "year": 2019,
    "doi": "10.1/X",
    "first_author": "Ann Lee 0001",
}


def _oa(**kw):
    base = {"openalex_id": "W9", "doi": "10.1/x", "title": PAPER["title"], "publication_year": 2019}
    return {**base, **kw}


def test_openalex_doi_match_needs_the_same_doi() -> None:
    look = {"lookup_kind": "doi", "openalex_id": "W9"}
    assert match_openalex(PAPER, look, _oa(), None, SM).accepted.method == "doi"
    other = match_openalex(PAPER, look, _oa(doi="10.9/other"), None, SM)
    assert other.accepted is None and "another DOI" in other.rejected


def test_title_match_applies_title_year_and_first_author_rules() -> None:
    look = {"lookup_kind": "title", "openalex_id": "W9"}
    ok = match_openalex(PAPER, look, _oa(doi=None), "Ann Lee", SM).accepted
    assert ok.method == "title" and ok.first_author_agrees is True
    far = match_openalex(PAPER, look, _oa(doi=None, publication_year=2023), "Ann Lee", SM)
    assert far.accepted is None and "year differs" in far.rejected
    title = match_openalex(
        PAPER, look, _oa(doi=None, title="Something else entirely"), "Ann Lee", SM
    )
    assert title.accepted is None and "similarity" in title.rejected
    who = match_openalex(PAPER, look, _oa(doi=None), "Zed Quux", SM)
    assert who.accepted is None and "surname" in who.rejected
    no_authors = match_openalex(PAPER, look, _oa(doi=None), None, SM).accepted
    assert (
        no_authors.first_author_agrees is None
        and no_authors.confidence <= SM.no_author_confidence_cap
    )


def test_s2_joins_by_doi_then_dblp_key_then_title() -> None:
    s2 = {"s2_corpus_id": 5, "title": PAPER["title"], "year": 2019, "doi": "10.1/X"}
    look = {"status": "matched", "s2_corpus_id": 5, "s2_dblp_key": None}
    assert match_s2(PAPER, look, s2, SM).accepted.method == "doi"
    by_key = {**look, "s2_dblp_key": "conf/c/X"}
    assert match_s2(PAPER, by_key, {**s2, "doi": None}, SM).accepted.method == "dblp-key"
    by_title = match_s2(PAPER, look, {**s2, "doi": None}, SM).accepted
    assert by_title.method == "title" and by_title.confidence <= SM.no_author_confidence_cap
    journal = match_s2(PAPER, look, {**s2, "doi": None, "year": 2024}, SM)
    assert journal.accepted is None and "another version" in journal.rejected
    assert match_s2(PAPER, {"status": "not_found"}, None, SM).accepted is None


def test_crossref_row_must_carry_the_same_doi() -> None:
    assert match_crossref(PAPER, {"doi": "10.1/x"}).accepted.method == "doi"
    assert match_crossref(PAPER, {"doi": "10.9/y"}).accepted is None
    assert match_crossref({**PAPER, "doi": None}, {"doi": "10.1/x"}).accepted is None


# -- §8.2 versions ----------------------------------------------------------------------------


def _ref(key: str, title: str, year: int, **kw) -> VersionRef:
    base = {
        "venue_id": "conf",
        "edition_id": f"ed{year}",
        "kind": "proceedings",
        "authors": frozenset({"a", "b"}),
        "embedding": (1.0, 0.0, 0.0),
    }
    return VersionRef(key=key, title=title, year=year, **{**base, **kw})


def test_conference_and_journal_version_merge() -> None:
    conf = _ref("c", "Fast Matching (Extended Abstract)", 2019)
    jour = _ref("j", "Fast Matching", 2021, venue_id="jour", edition_id="v21", kind="journal",
                embedding=(0.98, 0.2, 0.0))  # fmt: skip
    pair = score_pair(jour, conf, CFG)  # argument order does not matter
    assert (pair.earlier, pair.later) == ("c", "j")
    assert pair.verdict == "merge" and pair.score >= 0.85
    assert primary_version([conf, jour]).key == "j"  # the journal version is shown by default


def test_same_title_different_authors_is_not_a_candidate_and_does_not_merge() -> None:
    a = _ref("a", "Fast Matching", 2019, authors=frozenset({"a", "b"}))
    b = _ref("b", "Fast Matching", 2019, edition_id="other", authors=frozenset({"c", "d"}))
    assert list(candidate_pairs([a, b], CFG)) == []
    assert score_pair(a, b, CFG).verdict != "merge"


def test_one_shared_author_with_a_new_coauthor_is_only_uncertain() -> None:
    a = _ref("a", "Fast Matching", 2019, authors=frozenset({"a", "b"}))
    b = _ref("b", "Fast Matching", 2021, edition_id="x", authors=frozenset({"a", "c"}),
             embedding=(0.9, 0.4, 0.0))  # fmt: skip
    pair = score_pair(a, b, CFG)
    assert pair.verdict == "uncertain" and 0.5 <= pair.score < 0.85


def test_unrelated_embedding_and_authors_stay_below_report_band() -> None:
    a = _ref("a", "Fast Matching", 2019, authors=frozenset({"a", "b", "c", "d"}))
    b = _ref("b", "Fast Matching Again", 2021, edition_id="x", authors=frozenset({"a", "z"}),
             embedding=(0.0, 1.0, 0.0))  # fmt: skip
    assert score_pair(a, b, CFG).verdict == "ignored"


def test_two_papers_of_one_edition_and_numbered_parts_never_merge_by_score() -> None:
    same_edition = score_pair(
        _ref("a", "Fast Matching", 2019, edition_id="e"),
        _ref("b", "Fast Matching", 2019, edition_id="e"),
        CFG,
    )
    assert same_edition.verdict == "vetoed" and "same edition" in same_edition.reasons
    parts = score_pair(
        _ref("a", "Pumping Words I", 2019, edition_id="e1"),
        _ref("b", "Pumping Words II", 2020, edition_id="e2"),
        CFG,
    )
    assert parts.verdict == "vetoed"


def test_a_shared_doi_merges_outright() -> None:
    a = _ref("a", "One title", 2019, doi="10.1/ABC", authors=frozenset({"a"}))
    b = _ref("b", "A totally different title", 2020, doi="https://doi.org/10.1/abc",
             authors=frozenset({"z"}), edition_id="x")  # fmt: skip
    pairs = list(candidate_pairs([a, b], CFG))
    assert len(pairs) == 1
    scored = score_pair(*pairs[0], CFG)
    assert scored.verdict == "merge" and scored.method == "doi" and scored.score == 1.0


def test_one_external_record_is_extra_evidence() -> None:
    a = _ref("a", "Fast Matching", 2019, external=frozenset({("s2", "7")}))
    b = _ref("b", "Fast Matching", 2020, edition_id="x", external=frozenset({("s2", "7")}),
             embedding=(0.9, 0.4, 0.0), authors=frozenset({"a", "c"}))  # fmt: skip
    pair = score_pair(a, b, CFG)
    assert pair.features["extra"] == 1.0 and "same_external_record" in pair.reasons[0]


def test_citing_a_paper_of_the_same_kind_is_not_evidence_but_cross_kind_is() -> None:
    a = _ref("a", "Fast Matching", 2019, authors=frozenset({"a", "c"}), embedding=(0.9, 0.4, 0.0))
    b = _ref("b", "Fast Matching Revisited", 2021, edition_id="x", cites=frozenset({"a"}),
             authors=frozenset({"a", "d"}), embedding=(0.9, 0.4, 0.0))  # fmt: skip
    assert score_pair(a, b, CFG).features["extra"] == 0.0
    journal = _ref("b", "Fast Matching Revisited", 2021, edition_id="x", kind="journal",
                   cites=frozenset({"a"}), authors=frozenset({"a", "d"}),
                   embedding=(0.9, 0.4, 0.0))  # fmt: skip
    assert score_pair(a, journal, CFG).features["extra"] == 1.0


def test_special_issue_of_the_earlier_venue_is_evidence_for_a_journal_version() -> None:
    conf = _ref("c", "Fast Matching", 2019)
    jour = _ref("j", "Fast Matching", 2020, venue_id="jour", edition_id="v", kind="journal",
                special_issue_of="conf")  # fmt: skip
    assert score_pair(conf, jour, CFG).features["extra"] == 1.0


def test_grouping_never_puts_two_versions_of_one_edition_together() -> None:
    a = _ref("a", "Fast Matching", 2019, edition_id="e1")
    b = _ref("b", "Fast Matching", 2020, edition_id="e2")
    c = _ref("c", "Fast Matching", 2021, edition_id="e2")  # same edition as b
    versions = [a, b, c]
    pairs = [score_pair(x, y, CFG) for x, y in candidate_pairs(versions, CFG)]
    grouping = group_versions(versions, pairs, CFG)
    members = {}
    for key, founder in grouping.group_of.items():
        members.setdefault(founder, []).append(key)
    assert all(not ({"b", "c"} <= set(group)) for group in members.values())
    assert grouping.group_of["b"] == "a" or grouping.group_of["c"] == "a"


def test_grouping_is_transitive_and_the_earliest_version_founds_the_group() -> None:
    a = _ref("a", "Fast Matching", 2019, edition_id="e1")
    b = _ref("b", "Fast Matching", 2020, edition_id="e2")
    c = _ref("c", "Fast Matching", 2021, edition_id="e3")
    pairs = [score_pair(x, y, CFG) for x, y in candidate_pairs([a, b, c], CFG)]
    grouping = group_versions([a, b, c], pairs, CFG)
    assert set(grouping.group_of.values()) == {"a"}
    assert set(grouping.attach) == {"b", "c"}


# -- §8.3 authors -----------------------------------------------------------------------------

AC = AuthorsConfig()


def _dblp(*names: tuple[str, str]):
    return [
        {"position": i, "pid": pid, "name_raw": name}
        for i, (pid, name) in enumerate(names, start=1)
    ]


def _ext(*names: str) -> list[ExternalAuthor]:
    return [
        ExternalAuthor(position=i, author_id=f"A{i}", names=(n,)) for i, n in enumerate(names, 1)
    ]


def test_authors_align_by_position_when_the_lists_agree() -> None:
    result = align_authors(
        _dblp(("p1", "Ann Lee"), ("p2", "Bob Stone")), _ext("Ann Lee", "B. Stone"), AC
    )
    assert [(a.pid, a.external.author_id, a.method) for a in result] == [
        ("p1", "A1", "position"),
        ("p2", "A2", "position"),
    ]


def test_authors_align_by_name_when_the_lists_differ() -> None:
    result = align_authors(
        _dblp(("p1", "Ann Lee"), ("p2", "Bob Stone")),
        _ext("Bob Stone", "Extra Person", "Ann Lee"),
        AC,
    )
    by_pid = {a.pid: a for a in result}
    assert by_pid["p1"].external.author_id == "A3" and by_pid["p2"].external.author_id == "A1"
    assert all(a.method == "name" for a in result)
    missing = align_authors(_dblp(("p1", "Ann Lee"), ("p9", "Zed Quux")), _ext("Ann Lee"), AC)
    assert missing[1].external is None and missing[1].method == "none"


def _evidence(ext: str, pid: str, papers: int, orcid: bool = False):
    return [(f"{ext}-{pid}-{i}", ext, pid, orcid) for i in range(papers)]


def test_two_agreeing_papers_link_an_external_id() -> None:
    links, unlinked = map_external_authors(_evidence("A1", "p1", 2), AC)
    assert links["A1"].pid == "p1" and links["A1"].method == "shared-papers" and not unlinked


def test_one_paper_is_not_enough_unless_the_orcid_matches() -> None:
    links, unlinked = map_external_authors(_evidence("A1", "p1", 1), AC)
    assert not links and "only 1 paper" in unlinked[0].reason
    links, _ = map_external_authors(_evidence("A1", "p1", 1, orcid=True), AC)
    assert links["A1"].method == "orcid"


def test_conflicting_evidence_blocks_the_link() -> None:
    evidence = _evidence("A1", "p1", 3) + _evidence("A1", "p2", 2)  # 60 % < 80 %
    links, unlinked = map_external_authors(evidence, AC)
    assert not links and unlinked[0].reason == "papers point to different PIDs"
    assert unlinked[0].pids == {"p1": 3, "p2": 2}


def test_a_dominant_pid_wins_and_the_rest_is_recorded() -> None:
    evidence = _evidence("A1", "p1", 9) + _evidence("A1", "p2", 1)
    links, _ = map_external_authors(evidence, AC)
    assert links["A1"].pid == "p1" and links["A1"].competing == {"p2": 1}


def test_orcid_settles_a_conflict() -> None:
    evidence = _evidence("A1", "p1", 3) + _evidence("A1", "p2", 2, orcid=True)
    links, _ = map_external_authors(evidence, AC)
    assert links["A1"].pid == "p2" and links["A1"].method == "orcid"


def test_homonyms_stay_separate_authors() -> None:
    authors = [
        {"pid": "1/1", "name": "Ann Lee 0001", "name_variants": [], "orcid": None},
        {"pid": "5/5", "name": "Ann Lee 0002", "name_variants": [], "orcid": None},
    ]
    ids = {"1/1": "A1", "5/5": "A5"}
    rows = build_author_rows(authors, {}, ids.__getitem__)
    assert [r["dblp_pid"] for r in rows] == ["1/1", "5/5"]
    assert {r["display_name"] for r in rows} == {"Ann Lee"}
    assert rows[0]["author_id"] != rows[1]["author_id"]


def test_institution_prefers_the_ror() -> None:
    rows = [
        {"position": 0, "author_id": "A1", "author_name": "X", "institution_id": "I1",
         "institution_name": "Uni", "ror": "01abc", "country_code": "PT",
         "raw_affiliation": "Uni, PT"},
        {"position": 0, "author_id": "A1", "author_name": "X", "institution_id": "I2",
         "institution_name": "Lab", "ror": None, "country_code": "FR", "raw_affiliation": "Lab"},
    ]  # fmt: skip
    [author] = group_external_authors(rows)
    assert author.raw_affiliations == ("Uni, PT", "Lab")
    assert institution_of(author) == {"id": "ror:01abc", "name": "Uni", "country": "PT"}
    assert institution_of(None) is None


# -- citations --------------------------------------------------------------------------------


def test_citations_are_the_union_of_both_sources_and_lifted_to_works() -> None:
    rows, stats = build_citation_rows(
        [("o1", "o2"), ("o1", "o9"), ("o3", "o3")],
        [(1, 2), (2, 1)],
        {"o1": "W1", "o2": "W2", "o3": "W1"},  # o3 is another version of W1
        {1: "W1", 2: "W2"},
    )
    assert [(r["citing_work_id"], r["cited_work_id"], r["sources"]) for r in rows] == [
        ("W1", "W2", ["openalex", "s2"]),
        ("W2", "W1", ["s2"]),
    ]
    assert all(r["is_influential"] is None for r in rows)
    assert stats["self_citations_dropped"] == 1 and stats["edges_in_both_sources"] == 1
