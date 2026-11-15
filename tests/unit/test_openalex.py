"""OpenAlex harvest and parse (P1-02), on trimmed real answers from tests/fixtures/openalex."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import duckdb
import httpx
import pyarrow as pa
import pytest

from flatatlas.db import connect
from flatatlas.http import BudgetExhausted, SourceClient
from flatatlas.sources import openalex as oa
from helpers import FakeClock

FIXTURES = Path(__file__).parent.parent / "fixtures" / "openalex"
WORKS = json.loads((FIXTURES / "works.json").read_text(encoding="utf-8"))
SEARCHES = json.loads((FIXTURES / "title_searches.json").read_text(encoding="utf-8"))

W_ABSTRACT, W_TWO_INSTITUTIONS, W_NO_INSTITUTION, W_NO_AUTHOR_ID, W_NO_DOI = WORKS
# W_ABSTRACT has an abstract and four authors without institutions; W_TWO_INSTITUTIONS has one
# author with two institutions; W_NO_AUTHOR_ID has an author whose OpenAlex ID is null;
# W_NO_DOI has no DOI, no abstract and no references.


def client(settings, clock: FakeClock) -> SourceClient:
    return SourceClient(
        "openalex", settings, clock=clock.monotonic, sleep=clock.sleep, now=clock.now
    )


def doi_of(work: dict) -> str:
    return oa.normalize_doi(work["doi"])


def paper(key: str, *, doi: str | None, title: str = "A title", year: int | None = 2015):
    return oa.PaperRef(key, "dlt", year, title, oa.normalize_title(title), doi)


# -- abstracts and DOIs --------------------------------------------------------------------------


def test_abstract_is_rebuilt_in_position_order():
    text = oa.reconstruct_abstract(W_ABSTRACT["abstract_inverted_index"])
    n_words = sum(len(v) for v in W_ABSTRACT["abstract_inverted_index"].values())
    assert len(text.split(" ")) == n_words == 152
    index = W_ABSTRACT["abstract_inverted_index"]
    first = min(index, key=lambda w: min(index[w]))
    assert text.startswith(first)


def test_abstract_handles_repeated_words_gaps_and_empty_input():
    assert oa.reconstruct_abstract({"b": [1], "a": [0, 2]}) == "a b a"
    assert oa.reconstruct_abstract({"late": [5], "early": [1]}) == "early late"
    assert oa.reconstruct_abstract({}) is None
    assert oa.reconstruct_abstract(None) is None
    assert oa.reconstruct_abstract({"x": []}) is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://doi.org/10.1007/ABC_1", "10.1007/abc_1"),
        ("http://dx.doi.org/10.1/X", "10.1/x"),
        ("doi:10.1/x", "10.1/x"),
        ("10.1/x", "10.1/x"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_doi(raw, expected):
    assert oa.normalize_doi(raw) == expected


# -- parse_work ----------------------------------------------------------------------------------


def test_parse_work_basic_fields_and_short_ids():
    parsed = oa.parse_work(W_TWO_INSTITUTIONS, "2026-11-15T12:00:00+00:00")
    w = parsed.work
    assert w["openalex_id"] == "W1051743951"
    assert w["doi"] == "10.1007/978-3-319-19225-3_6"
    assert (w["publication_year"], w["cited_by_count"]) == (2015, 3)
    assert (w["first_page"], w["last_page"]) == ("70", "80")
    assert w["referenced_works_count"] == 17 and w["n_references_listed"] == 5  # trimmed fixture
    assert w["has_abstract"] is False and w["abstract_chars"] is None and parsed.abstract is None
    assert w["parser_version"] == oa.PARSER_VERSION
    assert [r["cited_openalex_id"] for r in parsed.references] == [
        r.rsplit("/", 1)[-1] for r in W_TWO_INSTITUTIONS["referenced_works"]
    ]
    assert {r["citing_openalex_id"] for r in parsed.references} == {"W1051743951"}


def test_one_author_with_several_institutions_gives_one_row_each():
    parsed = oa.parse_work(W_TWO_INSTITUTIONS)
    assert len(W_TWO_INSTITUTIONS["authorships"]) == 1
    rows = parsed.authorships
    assert len(rows) == 2
    assert {r["author_id"] for r in rows} == {"A5000448954"}
    assert {r["institution_id"] for r in rows} == {
        i["id"].rsplit("/", 1)[-1] for i in W_TWO_INSTITUTIONS["authorships"][0]["institutions"]
    }
    assert {r["country_code"] for r in rows} == {"SK"}
    assert all(r["ror"] and not r["ror"].startswith("http") for r in rows)
    assert all(r["raw_affiliation"] for r in rows)
    assert parsed.work["n_authors"] == 1
    assert parsed.work["n_authors_with_institution"] == 1
    assert parsed.work["n_authors_with_country"] == 1


def test_author_without_institution_keeps_one_row_with_the_raw_affiliation():
    parsed = oa.parse_work(W_NO_INSTITUTION)
    assert len(parsed.authorships) == 1
    row = parsed.authorships[0]
    assert row["institution_id"] is None and row["country_code"] is None
    assert row["raw_affiliation"] and "Kiev" in row["raw_affiliation"]
    assert parsed.work["n_authors_with_institution"] == 0
    assert parsed.work["n_authors_with_country"] == 0


def test_author_without_openalex_id_is_kept():
    parsed = oa.parse_work(W_NO_AUTHOR_ID)
    missing = [r for r in parsed.authorships if r["author_id"] is None]
    assert len(missing) == 1 and missing[0]["author_name"] == "Dmitry Dementyev"
    assert len(parsed.authorships) == len(W_NO_AUTHOR_ID["authorships"])


def test_work_with_abstract_returns_the_text_and_its_length():
    parsed = oa.parse_work(W_ABSTRACT)
    assert parsed.abstract and parsed.work["has_abstract"] is True
    assert parsed.work["abstract_chars"] == len(parsed.abstract)


def test_work_without_doi_or_references_parses():
    parsed = oa.parse_work(W_NO_DOI)
    assert parsed.work["doi"] is None
    assert parsed.references == [] and parsed.work["n_references_listed"] == 0


def test_topics_and_keywords_share_a_table_and_keep_their_rank():
    parsed = oa.parse_work(W_ABSTRACT)
    kinds = {t["kind"] for t in parsed.topics}
    assert kinds <= {"topic", "keyword"}
    topics = [t for t in parsed.topics if t["kind"] == "topic"]
    assert [t["rank"] for t in topics] == list(range(len(topics)))
    assert all(t["topic_id"] and t["topic_id"].startswith("T") for t in topics)


def test_a_nearly_empty_record_still_parses():
    parsed = oa.parse_work({"id": "https://openalex.org/W1"})
    assert parsed.work["openalex_id"] == "W1"
    assert parsed.authorships == [] and parsed.references == [] and parsed.topics == []
    assert parsed.work["has_abstract"] is False
    assert parsed.work["counts_by_year"] == []


# -- requests ------------------------------------------------------------------------------------


def test_doi_batches_are_unique_sorted_lowercase_and_at_most_the_batch_size():
    dois = [f"10.1007/X{i:03d}" for i in range(250)] + [
        "10.1007/x000",
        "10.1/has,comma",
        "10.1/a|b",
    ]
    batches = oa.doi_batches(dois, 100)
    assert [len(b) for b in batches] == [100, 100, 50]
    flat = [d for b in batches for d in b]
    assert flat == sorted(set(flat)) and all(d == d.lower() for d in flat)
    assert not any("," in d or "|" in d for d in flat)


def test_batch_params_use_doi_urls_and_the_select_list():
    params = oa.batch_params(["10.1/a", "10.1/b"])
    assert params["filter"] == "doi:https://doi.org/10.1/a|https://doi.org/10.1/b"
    assert params["per_page"] == 200 and params["select"] == oa.SELECT
    assert "abstract_inverted_index" in oa.SELECT and "referenced_works" in oa.SELECT


def test_title_query_drops_punctuation_that_is_filter_syntax():
    assert oa.title_query('A, B: "C" (D) | E-F') == "A B C D E-F"
    p = paper("k", doi=None, title="Hello, World: Again", year=2001)
    params = oa.title_params(p)
    assert params["filter"] == "title.search:Hello World Again,publication_year:2000|2001|2002"
    assert oa.title_params(paper("k", doi=None, year=None)) is None
    assert oa.title_params(paper("k", doi=None, title="!!!")) is None


def test_title_search_plan_is_capped_ordered_and_skips_papers_with_a_usable_doi():
    papers = [
        paper("b", doi=None, title="Bee"),
        paper("a", doi=None, title="Ay"),
        paper("c", doi="10.1/ok", title="See"),
        paper("d", doi="10.1/has,comma", title="Dee"),
    ]
    assert [p.dblp_key for p in oa.title_search_plan(papers, 10)] == ["a", "b", "d"]
    assert [p.dblp_key for p in oa.title_search_plan(papers, 2)] == ["a", "b"]
    assert oa.title_search_plan(papers, 0) == []


# -- title matching ------------------------------------------------------------------------------

HIT, NEAR_DUPLICATE, MISS = SEARCHES


def search_paper(search: dict, year: int) -> oa.PaperRef:
    return paper("k", doi=None, title=search["query_title"], year=year)


def test_title_hit_with_trailing_period_matches_with_high_confidence():
    work, score = oa.best_title_match(search_paper(HIT, 1993), HIT["results"])
    assert work is not None and work["id"] == HIT["results"][0]["id"]
    assert score >= oa.TITLE_MATCH_MIN


def test_the_exact_title_beats_a_near_duplicate_next_to_it():
    assert len(NEAR_DUPLICATE["results"]) >= 2
    work, score = oa.best_title_match(search_paper(NEAR_DUPLICATE, 2003), NEAR_DUPLICATE["results"])
    assert work is not None and work["publication_year"] == 2003 and score > 0.99


def test_a_miss_is_rejected_but_reports_the_best_score():
    work, score = oa.best_title_match(search_paper(MISS, 2005), MISS["results"])
    assert work is None and 0 < score < oa.TITLE_MATCH_MIN


def test_year_outside_the_slack_is_rejected():
    assert oa.best_title_match(search_paper(HIT, 1999), HIT["results"])[0] is None
    assert oa.best_title_match(search_paper(HIT, 1994), HIT["results"])[0] is not None


# -- a fake OpenAlex for the harvest tests -------------------------------------------------------


def serve_openalex(httpx_mock, *, works=WORKS, searches=SEARCHES):
    """Answer like the API: DOI filters return the fixture works whose DOI is asked for; title
    filters return the fixture search whose title matches."""
    calls = {"doi": 0, "title": 0}

    def answer(request: httpx.Request) -> httpx.Response:
        query = parse_qs(request.url.query.decode())
        flt = query["filter"][0]
        if flt.startswith("doi:"):
            calls["doi"] += 1
            asked = {oa.normalize_doi(p) for p in flt[4:].split("|")}
            found = [w for w in works if w["doi"] and oa.normalize_doi(w["doi"]) in asked]
            return httpx.Response(200, json={"meta": {"count": len(found)}, "results": found})
        calls["title"] += 1
        title = flt.split(",publication_year:")[0].removeprefix("title.search:")
        hits = [s for s in searches if s["query_title"] == title]
        results = hits[0]["results"] if hits else []
        return httpx.Response(200, json={"meta": {"count": len(results)}, "results": results})

    httpx_mock.add_callback(answer, is_reusable=True, is_optional=True)
    return calls


@pytest.fixture
def con(settings):
    connection = connect(settings.paths)
    yield connection
    connection.close()


def make_dblp_table(con: duckdb.DuckDBPyConnection, rows: list[dict]) -> None:
    table = pa.Table.from_pylist(
        rows,
        schema=pa.schema(
            [
                ("dblp_key", pa.string()),
                ("venue_id", pa.string()),
                ("year", pa.int16()),
                ("title", pa.string()),
                ("title_norm", pa.string()),
                ("doi", pa.string()),
                ("is_front_matter", pa.bool_()),
            ]
        ),
    )
    con.register("_t", table)
    con.execute("CREATE OR REPLACE TABLE stg_dblp_paper AS SELECT * FROM _t")
    con.unregister("_t")


def pilot_papers() -> list[oa.PaperRef]:
    return [
        paper("conf/x/two-inst", doi=doi_of(W_TWO_INSTITUTIONS), year=2015),
        paper("conf/x/abstract", doi=doi_of(W_ABSTRACT), year=1994),
        paper("conf/x/gone", doi="10.9999/not-in-openalex", year=2001),  # asked, not returned
        paper("conf/x/hit", doi=None, title=HIT["query_title"], year=1993),
        paper("conf/x/miss", doi=None, title=MISS["query_title"], year=2005),
        paper("conf/x/never", doi=None, title="Never searched, over the cap", year=2000),
    ]


def test_load_papers_skips_front_matter_and_samples_by_hash(con):
    rows = [
        {
            "dblp_key": f"conf/x/{i}",
            "venue_id": "dlt" if i % 2 else "ciaa",
            "year": 2000 + i,
            "title": f"T{i}",
            "title_norm": f"t{i}",
            "doi": f"10.1/{i}",
            "is_front_matter": i == 0,
        }
        for i in range(10)
    ]
    make_dblp_table(con, rows)
    everything = oa.load_papers(con)
    assert [p.dblp_key for p in everything] == [f"conf/x/{i}" for i in range(1, 10)]
    only_dlt = oa.load_papers(con, venue_ids=["dlt"])
    assert {p.venue_id for p in only_dlt} == {"dlt"}
    sample = oa.load_papers(con, limit=4)
    assert len(sample) == 4 and sample == oa.load_papers(con, limit=4)  # stable


# -- harvest then parse, offline -----------------------------------------------------------------


def test_harvest_then_parse_joins_answers_to_papers(settings, con, httpx_mock):
    calls = serve_openalex(httpx_mock)
    c = client(settings, FakeClock())
    papers = pilot_papers()

    stats = oa.harvest(con, c, papers, max_title_searches=2)
    assert calls == {"doi": 1, "title": 2}  # one batch for the three DOIs; two searches (cap 2)
    assert stats.batches == 1 and stats.works_returned == 2 and stats.searches == 2
    assert stats.papers_without_search == 1

    parsed = oa.parse_openalex(c, papers)
    rows = {r["dblp_key"]: r for r in parsed.lookup}
    assert rows["conf/x/two-inst"]["match_method"] == "doi-exact"
    assert rows["conf/x/two-inst"]["openalex_id"] == "W1051743951"
    assert rows["conf/x/two-inst"]["match_confidence"] == 1.0
    assert rows["conf/x/gone"]["fetched"] is True and rows["conf/x/gone"]["openalex_id"] is None
    assert rows["conf/x/hit"]["lookup_kind"] == "title"
    assert rows["conf/x/hit"]["openalex_id"] == HIT["results"][0]["id"].rsplit("/", 1)[-1]
    assert rows["conf/x/hit"]["match_method"].startswith("title-search")
    assert rows["conf/x/hit"]["match_confidence"] >= oa.TITLE_MATCH_MIN
    assert rows["conf/x/miss"]["fetched"] is True and rows["conf/x/miss"]["openalex_id"] is None
    assert rows["conf/x/never"]["fetched"] is False  # over the cap: not asked, so not "not found"

    assert parsed.stats["matched"] == 3 and parsed.stats["fetched"] == 5
    assert {a["dblp_key"] for a in parsed.abstracts} == {"conf/x/abstract"}
    assert parsed.abstracts[0]["source"] == "openalex" and parsed.abstracts[0]["n_chars"] > 100
    assert len(parsed.works) == 3


def test_parse_does_not_touch_the_network(settings, con, httpx_mock):
    serve_openalex(httpx_mock)
    c = client(settings, FakeClock())
    papers = pilot_papers()
    oa.harvest(con, c, papers, max_title_searches=3)
    before = len(httpx_mock.get_requests())
    oa.parse_openalex(c, papers)
    oa.parse_openalex(c, papers)
    assert len(httpx_mock.get_requests()) == before


def test_a_finished_harvest_is_a_no_op_and_restart_asks_the_cache(settings, con, httpx_mock):
    calls = serve_openalex(httpx_mock)
    c = client(settings, FakeClock())
    oa.harvest(con, c, pilot_papers(), max_title_searches=3)
    first = dict(calls)
    again = oa.harvest(con, c, pilot_papers(), max_title_searches=3)
    assert calls == first and again.batches == 0
    restarted = oa.harvest(con, c, pilot_papers(), max_title_searches=3, restart=True)
    assert calls == first  # everything came from the cache
    assert restarted.batches == restarted.batches_from_cache == 1
    assert restarted.searches == restarted.searches_from_cache == 3


def test_older_probes_with_another_select_are_ignored(settings, con, httpx_mock):
    serve_openalex(httpx_mock)
    c = client(settings, FakeClock())
    c.get("/works", {"filter": f"doi:https://doi.org/{doi_of(W_ABSTRACT)}", "select": "id,doi"})
    parsed = oa.parse_openalex(c, [paper("conf/x/abstract", doi=doi_of(W_ABSTRACT))])
    assert parsed.lookup[0]["fetched"] is False and parsed.lookup[0]["openalex_id"] is None


def test_parse_before_any_harvest_marks_everything_not_fetched(settings):
    c = client(settings, FakeClock())
    parsed = oa.parse_openalex(c, pilot_papers())
    assert not any(r["fetched"] for r in parsed.lookup) and parsed.works == []


def test_reference_candidates_exclude_pilot_works_and_count_citing_papers():
    refs = [
        {"citing_openalex_id": "W1", "cited_openalex_id": "W9"},
        {"citing_openalex_id": "W2", "cited_openalex_id": "W9"},
        {"citing_openalex_id": "W2", "cited_openalex_id": "W8"},
        {"citing_openalex_id": "W2", "cited_openalex_id": "W1"},  # a pilot work: not a candidate
    ]
    assert oa.reference_candidates(refs, {"W1", "W2"}) == [
        {"openalex_id": "W9", "n_citing_pilot_works": 2},
        {"openalex_id": "W8", "n_citing_pilot_works": 1},
    ]


def test_write_tables_round_trip_and_local_abstract_keeps_other_sources(settings, con, httpx_mock):
    serve_openalex(httpx_mock)
    c = client(settings, FakeClock())
    papers = pilot_papers()
    oa.harvest(con, c, papers, max_title_searches=3)
    parsed = oa.parse_openalex(c, papers)
    # an abstract another source already put in the table must survive
    oa.write_local_abstracts(
        con,
        settings.paths,
        "crossref",
        [
            {
                "dblp_key": "conf/x/hit",
                "openalex_id": None,
                "doi": "10.1/z",
                "source": "crossref",
                "text": "from crossref",
                "n_chars": 13,
            }
        ],
    )
    oa.write_tables(con, settings.paths, parsed)
    assert con.execute("SELECT count(*) FROM stg_openalex_lookup").fetchone()[0] == len(papers)
    assert con.execute("SELECT count(*) FROM stg_openalex_work").fetchone()[0] == 3
    sources = dict(con.execute("SELECT source, count(*) FROM local_abstract GROUP BY 1").fetchall())
    assert sources == {"crossref": 1, "openalex": 1}
    for name in oa.TABLES:
        assert (settings.paths.warehouse / "staging" / f"{name}.parquet").exists()
    assert (settings.paths.warehouse / "local" / "local_abstract.parquet").exists()
    # re-writing replaces the openalex rows, it does not duplicate them
    oa.write_tables(con, settings.paths, parsed)
    assert (
        con.execute("SELECT count(*) FROM local_abstract WHERE source='openalex'").fetchone()[0]
        == 1
    )


# -- the budget guard with the real cost table ---------------------------------------------------


def test_title_searches_stop_when_the_daily_budget_is_used_up_and_resume_next_day(
    settings, con, httpx_mock
):
    calls = serve_openalex(httpx_mock)
    clock = FakeClock()
    c = client(settings, clock)
    assert c.cfg.daily_budget_usd == 1.0 and c.cfg.costs["search"] == 0.001
    c.ledger.charge(0.9975)  # leaves room for two searches
    papers = [paper(f"k{i}", doi=None, title=f"Title number {i}") for i in range(5)]
    with pytest.raises(BudgetExhausted):
        oa.harvest(con, c, papers, max_title_searches=5)
    assert calls["title"] == 2
    assert c.ledger.spent_today_usd() == pytest.approx(0.9995)
    state = con.execute(
        "SELECT status, \"cursor\" FROM ops_harvest_state WHERE job_key LIKE 'title-search:%'"
    ).fetchone()
    assert state == ("interrupted", "2")

    clock.advance(days=1)  # next UTC day: the same command continues where it stopped
    oa.harvest(con, c, papers, max_title_searches=5)
    assert calls["title"] == 5  # 2 from the first day were cached, 3 new
    assert c.ledger.spent_today_usd() == pytest.approx(0.003)


def test_doi_batches_cost_the_list_price_and_singletons_are_free(settings, con, httpx_mock):
    serve_openalex(httpx_mock)
    c = client(settings, FakeClock())
    oa.harvest(con, c, [paper("k", doi=doi_of(W_ABSTRACT))], max_title_searches=0)
    assert c.ledger.spent_today_usd() == pytest.approx(0.0001)
    assert c.cfg.costs["singleton"] == 0.0


def test_the_api_key_is_sent_but_not_in_the_cached_url(settings, con, httpx_mock):
    serve_openalex(httpx_mock)
    c = client(settings, FakeClock())
    oa.harvest(con, c, [paper("k", doi=doi_of(W_ABSTRACT))], max_title_searches=0)
    (request,) = httpx_mock.get_requests()
    assert "api_key=" in str(request.url)
    cached_urls = [r.url for r in c.iter_cached("/works")]
    assert cached_urls and not any("api_key" in u for u in cached_urls)
