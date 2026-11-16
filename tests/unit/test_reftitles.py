"""Reference-title and background-title harvests (P1-05): batching, cache, parse, coverage."""

from __future__ import annotations

from urllib.parse import parse_qs

import duckdb
import httpx
import pyarrow as pa
import pytest

from flatatlas.db import connect, replace_table
from flatatlas.http import SourceClient
from flatatlas.sources import reftitles as rt
from helpers import FakeClock

N_CANDIDATES = 7  # candidate works W1..W7; "W7" is unknown to OpenAlex, "W6" has no title


@pytest.fixture
def con(settings):
    con = connect(settings.paths)
    con.execute(
        "CREATE TABLE stg_reference_candidates (openalex_id VARCHAR, n_citing_pilot_works INTEGER)"
    )
    con.executemany(
        "INSERT INTO stg_reference_candidates VALUES (?, ?)",
        [(f"W{i}", 10 - i) for i in range(1, N_CANDIDATES + 1)],
    )
    con.execute(
        "CREATE TABLE stg_openalex_work (openalex_id VARCHAR, title VARCHAR, "
        "publication_year SMALLINT, type VARCHAR)"
    )
    con.execute("INSERT INTO stg_openalex_work VALUES ('WP1', 'A pilot paper', 2001, 'article')")
    con.execute(
        "CREATE TABLE stg_openalex_reference (citing_openalex_id VARCHAR, "
        "cited_openalex_id VARCHAR, position INTEGER)"
    )
    refs = [("WP1", f"W{i}", i) for i in range(1, N_CANDIDATES + 1)] + [("WP2", "WP1", 1)]
    con.executemany("INSERT INTO stg_openalex_reference VALUES (?,?,?)", refs)
    yield con
    con.close()


def client(settings, clock: FakeClock) -> SourceClient:
    return SourceClient(
        "openalex", settings, clock=clock.monotonic, sleep=clock.sleep, now=clock.now
    )


def serve(httpx_mock):
    asked: list[list[str]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        query = parse_qs(request.url.query.decode())
        flt = query["filter"][0]
        assert query["select"] == [rt.SELECT]
        if flt.startswith("openalex:"):
            ids = flt.removeprefix("openalex:").split("|")
            asked.append(ids)
            results = [
                {
                    "id": f"https://openalex.org/{i}",
                    "title": None if i == "W6" else f"Title of {i}",
                    "publication_year": 1990,
                    "type": "article",
                }
                for i in ids
                if i != "W7"
            ]
            return httpx.Response(200, json={"meta": {"count": len(results)}, "results": results})
        page = int(query["page"][0])
        results = [
            {"id": f"https://openalex.org/B{page}{j}", "title": f"Graph paper {page}-{j}",
             "publication_year": 2000, "type": "article"}
            for j in range(2)
        ]  # fmt: skip
        return httpx.Response(200, json={"meta": {"count": 4}, "results": results})

    httpx_mock.add_callback(answer, is_reusable=True, is_optional=True)
    return asked


def test_candidates_come_most_cited_first_and_limit_takes_the_first(con):
    ids = rt.candidate_ids(con)
    assert ids == [f"W{i}" for i in range(1, 8)]
    assert rt.candidate_ids(con, 3) == ["W1", "W2", "W3"]


def test_batches_keep_order_and_params_name_the_filter_and_select():
    batches = rt.id_batches(["W1", "W2", "W3", "W4", "W5"], 2)
    assert batches == [["W1", "W2"], ["W3", "W4"], ["W5"]]
    params = rt.batch_params(batches[0])
    assert params == {"filter": "openalex:W1|W2", "per_page": 2, "select": rt.SELECT}


def test_estimate_counts_calls_and_checks_the_daily_budget():
    est = rt.estimate(15135, 100, 0.0001, spent=0.5, budget=1.0)
    assert est["calls"] == 152 and est["usd"] == pytest.approx(0.0152)
    assert est["fits_today"] is True
    assert rt.estimate(150000, 100, 0.0001, spent=0.9, budget=1.0)["fits_today"] is False
    assert rt.estimate(10, 100, 0.0, spent=0, budget=None)["fits_today"] is True


def test_harvest_is_batched_cached_and_resumable(settings, con, httpx_mock, clock):
    asked = serve(httpx_mock)
    c = client(settings, clock)
    ids = rt.candidate_ids(con)
    settings.sources["openalex"].batch_size = 3
    stats = rt.harvest_reference_titles(con, c, ids)
    assert [len(b) for b in asked] == [3, 3, 1]
    assert stats.batches == 3 and stats.works_returned == 6
    # a second run makes no request (the job is done, and the cache would answer anyway)
    again = rt.harvest_reference_titles(con, c, ids)
    assert again.batches == 0 and len(asked) == 3
    c.close()


def test_parse_joins_pilot_titles_and_candidates_and_keeps_unanswered_ones(
    settings, con, httpx_mock, clock
):
    serve(httpx_mock)
    c = client(settings, clock)
    rt.harvest_reference_titles(con, c, rt.candidate_ids(con))
    before = len(httpx_mock.get_requests())
    parsed = rt.parse_reference_titles(con, c)
    assert len(httpx_mock.get_requests()) == before  # parse reads the cache only
    rows = {r["openalex_id"]: r for r in parsed["rows"]}
    assert rows["WP1"]["source"] == "pilot" and rows["WP1"]["title"] == "A pilot paper"
    assert rows["W1"]["title"] == "Title of W1" and rows["W1"]["n_citing_pilot_works"] == 9
    assert rows["W6"]["fetched"] and rows["W6"]["title"] is None  # asked, answered without a title
    assert rows["W7"]["fetched"] and rows["W7"]["title"] is None  # asked, not returned at all
    assert parsed["n_asked"] == 7 and parsed["n_candidates"] == 7
    rt.write_reference_titles(con, settings.paths, parsed["rows"])
    cov = rt.coverage(con)
    # 8 reference edges (7 from WP1, 1 from WP2); titles for W1-W5, WP1 twice: W1..W5 + WP1 = 6
    assert cov["edges"] == 8 and cov["edges_with_title"] == 6
    assert cov["edge_share"] == pytest.approx(0.75)
    assert cov["cited_works"] == 8 and cov["cited_works_with_title"] == 6
    c.close()


def test_parse_ignores_answers_made_with_another_select(settings, con, httpx_mock, clock):
    c = client(settings, clock)
    httpx_mock.add_response(json={"results": [{"id": "https://openalex.org/W1", "title": "x"}]})
    c.get("/works", {"filter": "openalex:W1", "select": "id,title", "per_page": 1})
    assert rt.read_cached_titles(c).asked == set()
    c.close()


def test_background_titles_page_through_one_seeded_sample(settings, con, httpx_mock, clock):
    serve(httpx_mock)
    c = client(settings, clock)
    flt = "primary_topic.subfield.id:1703,type:article"
    stats = rt.harvest_background_titles(con, c, filter_=flt, n_titles=400, per_page=200, seed=7)
    assert stats.batches == 2 and stats.works_returned == 4
    sent = [parse_qs(r.url.query.decode()) for r in httpx_mock.get_requests()]
    assert [q["page"] for q in sent] == [["1"], ["2"]]
    assert all(q["sample"] == ["400"] and q["seed"] == ["7"] for q in sent)
    rows = rt.parse_background_titles(c, filter_=flt)
    assert [r["openalex_id"] for r in rows] == ["B10", "B11", "B20", "B21"]
    assert rt.parse_background_titles(c, filter_="another filter") == []
    rt.write_background_titles(con, settings.paths, rows)
    assert con.execute("SELECT count(*) FROM stg_background_title").fetchone()[0] == 4
    c.close()


def test_schemas_match_what_the_tables_hold(con, settings):
    replace_table(
        con, "t", pa.Table.from_pylist([], schema=rt.SCHEMA), settings.paths.warehouse / "t.parquet"
    )
    names = [r[0] for r in con.execute("DESCRIBE t").fetchall()]
    assert names == [f.name for f in rt.SCHEMA]
    assert isinstance(con, duckdb.DuckDBPyConnection)
