"""The data-quality checks fail loudly on broken core tables (P1-04)."""

from __future__ import annotations

import pyarrow as pa
import pytest

from flatatlas import quality
from flatatlas.db import connect
from flatatlas.ids import IdRegistry
from flatatlas.resolve.config import QualityConfig
from flatatlas.resolve.stage import write_tables
from flatatlas.resolve.works import resolve_corpus
from flatatlas.settings import Paths
from resolve_inputs import config, make_inputs, venue_registry

# The synthetic corpus has few matches; only the structural checks matter here.
LENIENT = QualityConfig(
    min_share_openalex=0.0, min_share_s2=0.0, min_share_crossref_of_doi=0.0, max_uncertain_pairs=10
)


@pytest.fixture
def con(tmp_path):
    inputs = make_inputs()
    registry = IdRegistry()
    resolved = resolve_corpus(inputs, config(), venue_registry(), registry)
    paths = Paths(tmp_path)
    connection = connect(paths)
    write_tables(connection, paths, resolved, inputs, registry)
    connection.register("_stg", pa.Table.from_pylist(inputs.papers))
    connection.execute("CREATE TABLE stg_dblp_paper AS SELECT * FROM _stg")
    yield connection
    connection.close()


def results(con, cfg=LENIENT):
    return {r.check: r for r in quality.run_checks(con, cfg)}


def failed(con, cfg=LENIENT) -> set[str]:
    return {name for name, r in results(con, cfg).items() if not r.passed}


def test_clean_tables_pass_every_check(con) -> None:
    assert failed(con) == set()


def test_missing_tables_are_reported(tmp_path) -> None:
    connection = connect(Paths(tmp_path))
    with pytest.raises(LookupError, match="flatatlas resolve"):
        quality.run_checks(connection, LENIENT)


def test_a_doi_on_two_works_fails(con) -> None:
    con.execute(
        "UPDATE core_version SET doi = '10.1/a19' WHERE dblp_key IN ('conf/c/A19','conf/c/B19')"
    )
    assert "unique_dois_across_works" in failed(con)


def test_a_version_without_a_venue_or_year_fails(con) -> None:
    con.execute("UPDATE core_version SET year = NULL WHERE dblp_key = 'conf/c/B19'")
    assert "versions_have_venue_and_year" in failed(con)
    con.execute(
        "UPDATE core_version SET year = 2019, venue_id = 'VMISSING' WHERE dblp_key = 'conf/c/B19'"
    )
    assert "versions_have_venue_and_year" in failed(con)


def test_an_orphan_authorship_fails(con) -> None:
    con.execute("UPDATE core_authorship SET author_id = 'ANOBODY' WHERE position = 1")
    assert "no_orphan_authorships" in failed(con)


def test_edition_counts_must_equal_staging(con) -> None:
    con.execute("DELETE FROM core_version WHERE dblp_key = 'conf/c/P19a'")
    assert "edition_counts_match_staging" in failed(con)


def test_an_author_with_two_pids_or_a_shared_openalex_id_fails(con) -> None:
    con.execute("UPDATE core_author SET dblp_pid = '2/2' WHERE dblp_pid = '3/3'")
    assert "one_pid_per_author" in failed(con)


def test_an_openalex_id_on_two_authors_fails(con) -> None:
    con.execute("UPDATE core_author SET openalex_ids = ['A100'] WHERE dblp_pid IN ('1/1', '3/3')")
    assert "one_pid_per_author" in failed(con)


def test_inconsistent_works_fail(con) -> None:
    con.execute("UPDATE core_work SET year = year + 1")
    assert "works_are_consistent" in failed(con)


def test_a_merged_away_id_in_a_table_fails(con) -> None:
    con.execute(
        "UPDATE core_version SET work_id = "
        "(SELECT atlas_id FROM core_id_registry WHERE merged_into IS NOT NULL LIMIT 1) "
        "WHERE dblp_key = 'conf/c/A19'"
    )
    assert "no_merged_away_ids_in_tables" in failed(con)


def test_a_bad_citation_edge_fails(con) -> None:
    con.execute("INSERT INTO core_citation VALUES ('WX', 'WY', ['s2'], NULL)")
    assert "citations_are_valid" in failed(con)


def test_source_shares_are_compared_with_their_thresholds(con) -> None:
    strict = QualityConfig(min_share_openalex=0.99, min_share_s2=0.0, min_share_crossref_of_doi=0.0)
    assert "share_matched_openalex" in failed(con, strict)
    assert results(con, strict)["share_matched_openalex"].value == pytest.approx(2 / 6)


def test_too_many_uncertain_pairs_fail(con) -> None:
    con.execute("UPDATE core_version_pair SET verdict = 'uncertain'")
    tight = QualityConfig(max_uncertain_pairs=0, min_share_openalex=0, min_share_s2=0,
                          min_share_crossref_of_doi=0)  # fmt: skip
    assert "uncertain_version_pairs" in failed(con, tight)


def test_the_merge_confidence_histogram_is_informational_and_recorded(con) -> None:
    rs = results(con)
    hist = {n: r for n, r in rs.items() if n.startswith("merge_confidence")}
    assert rs["merge_confidence_anchor"].value == 5
    assert sum(r.value for n, r in hist.items() if n.startswith("merge_confidence_hist")) == 1
    assert all(r.passed and r.threshold is None for r in hist.values())
    quality.record(con, "run-1", list(rs.values()))
    stored = con.execute(
        "SELECT count(*) FROM ops_quality_report WHERE run_id = 'run-1'"
    ).fetchone()
    assert stored[0] == len(rs)
    quality.record(con, "run-1", list(rs.values()))  # recording again replaces, never duplicates
    assert con.execute("SELECT count(*) FROM ops_quality_report WHERE run_id = 'run-1'").fetchone()[
        0
    ] == len(rs)
