"""Crossref harvest and parse (P1-02), on trimmed real answers from tests/fixtures/crossref."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pyarrow as pa
import pytest

from flatatlas.db import connect
from flatatlas.http import SourceClient
from flatatlas.sources import crossref as cr
from helpers import FAKE_EMAIL, FakeClock

FIXTURES = Path(__file__).parent.parent / "fixtures" / "crossref"
RECORDS = json.loads((FIXTURES / "works.json").read_text(encoding="utf-8"))
JATS = json.loads((FIXTURES / "jats_abstracts.json").read_text(encoding="utf-8"))
BY_DOI = {r["DOI"].lower(): r for r in RECORDS}
LNCS, WORLD_SCIENTIFIC, *_ = RECORDS


def client(settings, clock: FakeClock) -> SourceClient:
    return SourceClient(
        "crossref", settings, clock=clock.monotonic, sleep=clock.sleep, now=clock.now
    )


@pytest.fixture
def con(settings):
    connection = connect(settings.paths)
    yield connection
    connection.close()


def serve_crossref(httpx_mock):
    """GET /works/<doi>: the fixture record, or 404 for any other DOI."""
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        doi = request.url.path.removeprefix("/works/").lower()
        asked.append(doi)
        if doi in BY_DOI:
            return httpx.Response(200, json={"status": "ok", "message": BY_DOI[doi]})
        return httpx.Response(404, text="Resource not found.")

    httpx_mock.add_callback(answer, is_reusable=True, is_optional=True)
    return asked


# -- JATS ----------------------------------------------------------------------------------------


def test_jats_heading_called_abstract_is_dropped_and_whitespace_collapsed():
    text = cr.strip_jats(JATS["10.1515/comp-2017-0004"])
    assert text.startswith("In this work we present the algorithms")
    assert "<" not in text and "Abstract" not in text[:20]
    assert "\n" not in text and "\t" not in text and "  " not in text


def test_jats_entities_are_decoded_after_the_tags_are_removed():
    raw = JATS["10.46298/dmtcs.9063"]
    assert "&lt;" in raw
    text = cr.strip_jats(raw)
    assert "&lt;" not in text and "|u|<|v|" in text.replace(" ", "").replace("\\vert", "|")
    assert "<jats" not in text and "</" not in text


def test_jats_with_inline_markup_keeps_the_words():
    text = cr.strip_jats(JATS["10.1145/3632915"])
    assert text.startswith("While current bug detection techniques")
    assert "<" not in text and ">" not in text


def test_jats_edge_cases():
    assert cr.strip_jats(None) is None
    assert cr.strip_jats("") is None
    assert cr.strip_jats("<jats:p> </jats:p>") is None
    assert cr.strip_jats("<jats:title>Abstract</jats:title>") is None
    sectioned = (
        "<jats:sec><jats:title>Background</jats:title>"
        "<jats:p>A <jats:italic>b</jats:italic>.</jats:p></jats:sec>"
    )
    assert cr.strip_jats(sectioned) == "Background A b."
    assert cr.strip_jats("plain text, no markup") == "plain text, no markup"


# -- dates and records ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "block, expected",
    [
        ({"date-parts": [[2019, 3, 5]]}, "2019-03-05"),
        ({"date-parts": [[2019, 3]]}, "2019-03"),
        ({"date-parts": [[2019]]}, "2019"),
        ({"date-parts": [[None]]}, None),
        ({"date-parts": [[]]}, None),
        ({}, None),
        (None, None),
    ],
)
def test_date_from_parts(block, expected):
    assert cr.date_from_parts(block) == expected


def test_parse_message_reads_pages_dates_and_reference_counts():
    row, abstract = cr.parse_message(LNCS, "2026-11-15T12:00:00+00:00")
    assert abstract is None and row["has_abstract"] is False
    assert row["doi"] == LNCS["DOI"].lower()
    assert row["page"] == "213-225" and row["first_page"] == "213"
    assert row["issued_year"] == LNCS["issued"]["date-parts"][0][0]
    assert row["reference_count"] == 17 and row["n_references_listed"] == 5  # trimmed fixture
    assert row["container_titles"][0] == "Lecture Notes in Computer Science"
    assert row["publisher"] and row["crossref_type"] == "book-chapter"


def test_parse_message_for_a_record_without_references():
    row, _ = cr.parse_message(WORLD_SCIENTIFIC)
    assert row["reference_count"] == 0 and row["n_references_listed"] == 0
    assert row["container_titles"] == ["Developments In Language Theory"]


def test_a_message_with_an_abstract_returns_the_plain_text():
    message = {**LNCS, "abstract": JATS["10.1515/comp-2017-0004"]}
    row, abstract = cr.parse_message(message)
    assert row["has_abstract"] is True and row["abstract_chars"] == len(abstract)
    assert abstract.startswith("In this work")


def test_a_nearly_empty_message_parses():
    row, abstract = cr.parse_message({"DOI": "10.1/X"})
    assert row["doi"] == "10.1/x" and abstract is None
    assert row["page"] is None and row["first_page"] is None and row["issued_year"] is None


# -- which DOIs ----------------------------------------------------------------------------------


def test_arxiv_dois_are_not_asked():
    assert cr.is_crossref_doi("10.1007/x") and not cr.is_crossref_doi("10.48550/arXiv.1234")


def seed_warehouse(con, *, abstract_for: set[str] = frozenset()):
    """Four DBLP papers: a complete OpenAlex match, one without abstract, one not matched, one
    without DOI."""
    con.execute(
        """CREATE OR REPLACE TABLE stg_dblp_paper AS SELECT * FROM (VALUES
          ('k/complete',  'dlt',  2015, '10.1/complete',  false),
          ('k/noabs',     'dlt',  2016, '10.1/noabs',     false),
          ('k/missing',   'ciaa', 2017, '10.1/missing',   false),
          ('k/nodoi',     'ciaa', 2018, NULL,             false),
          ('k/front',     'ciaa', 2018, '10.1/front',     true),
          ('k/arxiv',     'ciaa', 2019, '10.48550/arxiv.1', false)
        ) t(dblp_key, venue_id, year, doi, is_front_matter)"""
    )
    con.execute(
        """CREATE OR REPLACE TABLE stg_openalex_lookup AS SELECT * FROM (VALUES
          ('k/complete', 'W1'), ('k/noabs', 'W2'), ('k/missing', NULL::VARCHAR)
        ) t(dblp_key, openalex_id)"""
    )
    con.execute(
        """CREATE OR REPLACE TABLE stg_openalex_work AS SELECT * FROM (VALUES
          ('W1', true,  '1', '2015-01-01', 3),
          ('W2', false, '1', '2016-01-01', 3)
        ) t(openalex_id, has_abstract, first_page, publication_date, n_references_listed)"""
    )


def test_dois_needing_crossref_are_those_missing_or_incomplete_in_openalex(con):
    seed_warehouse(con)
    assert cr.dois_needing_crossref(con) == ["10.1/missing", "10.1/noabs"]
    assert cr.dois_needing_crossref(con, venue_ids=["ciaa"]) == ["10.1/missing"]
    assert len(cr.dois_needing_crossref(con, limit=1)) == 1


# -- harvest and parse, offline ------------------------------------------------------------------


def test_harvest_asks_each_doi_once_and_remembers_404s(settings, con, httpx_mock):
    asked = serve_crossref(httpx_mock)
    c = client(settings, FakeClock())
    dois = [LNCS["DOI"].lower(), "10.9999/unknown", WORLD_SCIENTIFIC["DOI"].lower()]
    stats = cr.harvest(con, c, dois)
    assert (stats.asked, stats.found, stats.not_found) == (3, 2, 1)
    assert sorted(asked) == sorted(dois)
    again = cr.harvest(con, c, dois, restart=True)
    assert again.from_cache == 3 and len(asked) == 3  # all three from the cache, 404 included


def test_harvest_sends_the_mailto_and_never_caches_it(settings, con, httpx_mock):
    serve_crossref(httpx_mock)
    c = client(settings, FakeClock())
    cr.harvest(con, c, [LNCS["DOI"].lower()])
    (request,) = httpx_mock.get_requests()
    assert f"mailto={FAKE_EMAIL.replace('@', '%40')}" in str(request.url)
    assert not any("mailto" in r.url for r in c.iter_cached("/works"))


def test_harvest_is_resumable_by_cursor(settings, con, httpx_mock, monkeypatch):
    serve_crossref(httpx_mock)
    monkeypatch.setattr(cr, "PAGE_SIZE", 2)
    c = client(settings, FakeClock())
    dois = [f"10.9999/n{i}" for i in range(5)]
    stats = cr.harvest(con, c, dois)
    assert stats.asked == 5
    state = con.execute(
        "SELECT status, n_items FROM ops_harvest_state WHERE source = 'crossref'"
    ).fetchone()
    assert state == ("done", 5)


def test_parse_joins_papers_to_cached_records_and_collects_abstracts(settings, con, httpx_mock):
    serve_crossref(httpx_mock)
    c = client(settings, FakeClock())
    with_abstract = {
        **LNCS,
        "DOI": "10.1515/comp-2017-0004",
        "abstract": JATS["10.1515/comp-2017-0004"],
    }
    BY_DOI["10.1515/comp-2017-0004"] = with_abstract
    try:
        dois = [LNCS["DOI"].lower(), "10.1515/comp-2017-0004", "10.9999/unknown"]
        cr.harvest(con, c, dois)
        pairs = [
            ("k/lncs", LNCS["DOI"]),
            ("k/abs", "10.1515/COMP-2017-0004"),
            ("k/abs-twin", "10.1515/comp-2017-0004"),  # same DOI twice parses once
            ("k/unknown", "10.9999/unknown"),
            ("k/never-asked", "10.1/never"),
            ("k/arxiv", "10.48550/arxiv.1"),
        ]
        parsed = cr.parse_crossref(c, pairs)
    finally:
        del BY_DOI["10.1515/comp-2017-0004"]
    assert parsed.stats["found"] == 2 and parsed.stats["not_found"] == 1
    assert parsed.stats["not_fetched"] == 1 and parsed.stats["skipped_not_crossref"] == 1
    assert [a["dblp_key"] for a in parsed.abstracts] == ["k/abs", "k/abs-twin"]
    assert all(
        a["source"] == "crossref" and a["text"].startswith("In this work") for a in parsed.abstracts
    )
    assert {w["doi"] for w in parsed.works} == {LNCS["DOI"].lower(), "10.1515/comp-2017-0004"}


def test_write_tables_keeps_the_openalex_abstracts(settings, con):
    from flatatlas.sources import openalex as oa

    oa.write_local_abstracts(
        con,
        settings.paths,
        "openalex",
        [
            {
                "dblp_key": "k/1",
                "openalex_id": "W1",
                "doi": "10.1/a",
                "source": "openalex",
                "text": "kept",
                "n_chars": 4,
            }
        ],
    )
    row, _ = cr.parse_message(LNCS)
    parsed = cr.ParsedCrossref(
        works=[row],
        abstracts=[
            {
                "dblp_key": "k/2",
                "openalex_id": None,
                "doi": "10.1/b",
                "source": "crossref",
                "text": "new",
                "n_chars": 3,
            }
        ],
    )
    cr.write_tables(con, settings.paths, parsed)
    cr.write_tables(con, settings.paths, parsed)  # idempotent
    assert dict(
        con.execute("SELECT source, count(*) FROM local_abstract GROUP BY 1").fetchall()
    ) == {
        "openalex": 1,
        "crossref": 1,
    }
    assert con.execute("SELECT count(*) FROM stg_crossref_work").fetchone()[0] == 1
    assert pa.types.is_list(cr.SCHEMA.field("container_titles").type)
