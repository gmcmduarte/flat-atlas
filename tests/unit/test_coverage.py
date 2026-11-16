"""The coverage report (P1-02): numbers from seeded warehouse tables, and the Markdown."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from flatatlas import coverage
from flatatlas.db import connect
from flatatlas.sources import crossref as cr
from flatatlas.sources import openalex as oa

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def con(settings):
    connection = connect(settings.paths)
    yield connection
    connection.close()


def seed(con, *, with_crossref: bool = True) -> None:
    """Ten DBLP papers in two venues and two decades.

    dlt 1990s:  a (no DOI, title match), b (no DOI, searched, not found)
    dlt 2010s:  c (DOI, complete in OpenAlex, abstract), d (DOI, matched, no refs/affiliation),
                e (DOI, asked, not found), f (DOI, not fetched yet)
    ciaa 2010s: g (DOI, matched, Crossref has refs and an abstract), front (front matter)
    """
    con.execute(
        """CREATE OR REPLACE TABLE stg_dblp_paper AS SELECT * FROM (VALUES
          ('a', 'dlt', 1995, NULL,   false), ('b', 'dlt', 1996, NULL, false),
          ('c', 'dlt', 2015, '10.1/c', false), ('d', 'dlt', 2016, '10.1/d', false),
          ('e', 'dlt', 2017, '10.1/e', false), ('f', 'dlt', 2018, '10.1/f', false),
          ('g', 'ciaa', 2015, '10.1/g', false), ('front', 'ciaa', 2015, '10.1/fr', true)
        ) t(dblp_key, venue_id, year, doi, is_front_matter)"""
    )
    con.execute(
        """CREATE OR REPLACE TABLE stg_openalex_lookup AS SELECT * FROM (VALUES
          ('a', true, 'W1', 'title-search>=0.95'), ('b', true, NULL::VARCHAR, NULL::VARCHAR),
          ('c', true, 'W2', 'doi-exact'), ('d', true, 'W3', 'doi-exact'),
          ('e', true, NULL, NULL), ('g', true, 'W4', 'doi-exact')
        ) t(dblp_key, fetched, openalex_id, match_method)"""
    )
    con.execute(
        """CREATE OR REPLACE TABLE stg_openalex_work AS SELECT * FROM (VALUES
          ('W1', false, 0, 0, 0, '1'), ('W2', true, 20, 3, 3, '1'),
          ('W3', false, 0, 0, 0, NULL), ('W4', false, 0, 2, 2, '1')
        ) t(openalex_id, has_abstract, n_references_listed, n_authors_with_institution,
            n_authors_with_country, first_page)"""
    )
    if with_crossref:
        con.execute(
            """CREATE OR REPLACE TABLE stg_crossref_work AS SELECT * FROM (VALUES
              ('10.1/g', 12, '5'), ('10.1/f', 4, '9')
            ) t(doi, n_references_listed, first_page)"""
        )
        con.execute(
            """CREATE OR REPLACE TABLE local_abstract AS SELECT * FROM (VALUES
              ('c', 'W2', '10.1/c', 'openalex', 'text', 4),
              ('g', NULL, '10.1/g', 'crossref', 'text', 4)
            ) t(dblp_key, openalex_id, doi, source, "text", n_chars)"""
        )


def cell(cov, venue: str, decade: int) -> dict:
    return next(r for r in cov.cells if r["venue_id"] == venue and r["decade"] == decade)


def test_cells_count_papers_matches_abstracts_and_references(con):
    seed(con)
    cov = coverage.compute(con, now=NOW)
    dlt90 = cell(cov, "dlt", 1990)
    assert (dlt90["papers"], dlt90["with_doi"], dlt90["fetched"], dlt90["matched"]) == (2, 0, 2, 1)
    assert (dlt90["nodoi_fetched"], dlt90["nodoi_matched"]) == (2, 1)

    dlt10 = cell(cov, "dlt", 2010)
    assert (dlt10["papers"], dlt10["with_doi"]) == (4, 4)
    assert (dlt10["fetched"], dlt10["doi_fetched"], dlt10["doi_matched"]) == (3, 3, 2)
    assert dlt10["abs_openalex"] == 1 and dlt10["abs_crossref"] == 0 and dlt10["abs_any"] == 1
    assert dlt10["refs_openalex"] == 1 and dlt10["has_affiliation"] == 1
    assert dlt10["has_pages"] == 2  # c from OpenAlex and f from Crossref (not matched, not fetched)

    ciaa = cell(cov, "ciaa", 2010)
    assert ciaa["papers"] == 1  # front matter is not counted
    assert ciaa["refs_openalex"] == 0 and ciaa["refs_crossref"] == 1 and ciaa["refs_any"] == 1
    assert ciaa["abs_crossref"] == 1 and ciaa["abs_any"] == 1
    assert ciaa["has_affiliation"] == 1 and ciaa["has_country"] == 1


def test_totals_and_venue_rows_add_up(con):
    seed(con)
    cov = coverage.compute(con, now=NOW)
    t = cov.total
    assert t["papers"] == 7 and t["with_doi"] == 5 and t["fetched"] == 6
    assert t["doi_matched"] == 3 and t["doi_fetched"] == 4  # c, d, g of c, d, e, g
    assert t["matched"] == 4
    assert sum(r["papers"] for r in cov.venues) == t["papers"]
    assert sum(r["papers"] for r in cov.cells) == t["papers"]
    assert [r["venue_id"] for r in cov.venues] == ["ciaa", "dlt"]
    assert cov.missing_stages == []


def test_missing_optional_tables_are_reported_not_fatal_and_leave_no_trace(con):
    seed(con, with_crossref=False)
    cov = coverage.compute(con, now=NOW)
    assert sorted(cov.missing_stages) == ["parse crossref", "parse openalex"]
    assert cov.total["abs_crossref"] == 0 and cov.total["refs_crossref"] == 0
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert "stg_crossref_work" not in tables and "local_abstract" not in tables


def test_missing_required_tables_name_the_command_to_run(con):
    with pytest.raises(LookupError, match="parse dblp"):
        coverage.compute(con)


def test_render_states_the_headline_numbers_and_warns_about_partial_runs(con):
    seed(con)
    text = coverage.render(coverage.compute(con, now=NOW))
    assert text.startswith("# Coverage report: pilot venues")
    assert "Generated 2026-11-15 12:00 UTC" in text
    assert "**DOI match rate:** 3 of 4 fetched papers with a DOI are in OpenAlex (75%)" in text
    assert "**Title-search match rate:** 1 of 2" in text
    assert "**Partial run:** 1 of 7 papers have not been looked up" in text
    assert "| dlt | 2010s | 4 |" in text and "| ciaa | 2010s | 1 |" in text
    assert "Abstract OA" in text and "Refs any" in text


def test_render_of_a_complete_run_has_no_warnings(con):
    seed(con)
    con.execute("UPDATE stg_openalex_lookup SET fetched = true")
    con.execute("INSERT INTO stg_openalex_lookup VALUES ('f', true, NULL, NULL)")
    text = coverage.render(coverage.compute(con, now=NOW))
    assert "Partial run" not in text and "Not run yet" not in text


def test_percentages_do_not_divide_by_zero():
    assert coverage.pct(0, 0) == "–"
    assert coverage.pct(1, 3) == "33%"
    assert coverage.pct(3, 3) == "100%"


def test_the_stand_in_schemas_match_what_the_parsers_write():
    # the report queries these columns; a rename in a parser must break this test, not the report
    assert {"doi", "n_references_listed", "first_page"} <= set(cr.SCHEMA.names)
    assert {"dblp_key", "source", "text"} <= set(oa.LOCAL_ABSTRACT_SCHEMA.names)


def test_unmatched_dois_are_listed_with_their_key_and_year(con):
    seed(con)
    cov = coverage.compute(con, now=NOW)
    assert [(r["dblp_key"], r["year"], r["doi"]) for r in cov.unmatched_doi] == [
        ("e", 2017, "10.1/e")
    ]
    text = coverage.render(cov)
    assert "## DOIs asked and not returned (1)" in text and "| e | dlt | 2017 | 10.1/e |" in text
