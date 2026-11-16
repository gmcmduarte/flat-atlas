"""Semantic Scholar harvest and parse (P1-03), on trimmed real answers from tests/fixtures/s2."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from flatatlas.db import connect
from flatatlas.embed import store
from flatatlas.http import SourceClient
from flatatlas.sources import openalex as oa
from flatatlas.sources import s2
from helpers import FakeClock

FIXTURES = Path(__file__).parent.parent / "fixtures" / "s2"
BATCH = json.loads((FIXTURES / "batch.json").read_text(encoding="utf-8"))
MATCHES = json.loads((FIXTURES / "matches.json").read_text(encoding="utf-8"))

ANSWER_BY_DOI = {
    i.removeprefix("DOI:"): a for i, a in zip(BATCH["ids"], BATCH["answer"], strict=True)
}
FULL, TITLE_ONLY, NO_VECTOR, GONE_1, GONE_2 = list(ANSWER_BY_DOI)
# FULL: abstract, vector, 5 references. TITLE_ONLY: vector, no abstract, reference list null (the
# publisher elided it). NO_VECTOR: neither. GONE_*: DOIs S2 answered null for.
HIT, REJECTED, NONE = MATCHES


def client(settings, clock: FakeClock) -> SourceClient:
    return SourceClient(
        "semanticscholar", settings, clock=clock.monotonic, sleep=clock.sleep, now=clock.now
    )


def paper(key: str, *, doi: str | None, title: str = "A title", year: int | None = 2015):
    return oa.PaperRef(key, "dlt", year, title, oa.normalize_title(title), doi)


def match_paper(match: dict, key: str | None = None) -> oa.PaperRef:
    return paper(key or match["dblp_key"], doi=None, title=match["query_title"], year=match["year"])


# -- requests ------------------------------------------------------------------------------------


def test_the_configured_batch_size_is_the_verified_maximum(settings):
    assert settings.sources["semanticscholar"].batch_size == 500


def test_doi_batches_are_unique_sorted_lowercase_and_at_most_the_batch_size():
    batches = s2.doi_batches(["10.1/B", "10.1/a", "10.1/b", "", "10.1/c"], 2)
    assert batches == [["10.1/a", "10.1/b"], ["10.1/c"]]
    assert s2.doi_batches([], 500) == []


def test_batch_body_uses_the_doi_prefix_and_never_dblp():
    assert s2.batch_body(["10.1/a"]) == {"ids": ["DOI:10.1/a"]}  # `DBLP:` IDs answer null


def test_the_field_list_asks_for_the_embedding_and_not_the_edge_flag():
    fields = s2.FIELDS.split(",")
    assert "embedding.specter_v2" in fields and "references.corpusId" in fields
    assert "references.isInfluential" not in fields  # HTTP 400 on the batch endpoint


def test_match_params_collapse_whitespace_and_skip_empty_titles():
    p = paper("k", doi=None, title="Two   words\n here")
    assert s2.match_params(p) == {"query": "Two words here", "fields": s2.FIELDS}
    assert s2.match_params(paper("k", doi=None, title="  ")) is None


def test_title_match_plan_takes_papers_without_a_returned_doi_in_key_order_with_a_cap():
    answers = s2.CachedAnswers(by_doi={"10.1/ok": ("t", {"corpusId": 1}), "10.1/null": ("t", None)})
    papers = [
        paper("d", doi=None, title="Dee"),
        paper("a", doi="10.1/null", title="Ay"),  # asked, S2 answered null
        paper("b", doi="10.1/ok", title="Bee"),  # returned: no title match needed
        paper("c", doi="10.1/never-asked", title="Cee"),
    ]
    plan, left_out = s2.title_match_plan(papers, answers, 10)
    assert [p.dblp_key for p in plan] == ["a", "c", "d"] and left_out == 0
    plan, left_out = s2.title_match_plan(papers, answers, 2)
    assert [p.dblp_key for p in plan] == ["a", "c"] and left_out == 1


# -- parsing one item ----------------------------------------------------------------------------


def test_parse_item_with_abstract_vector_and_references():
    parsed = s2.parse_item(ANSWER_BY_DOI[FULL], "2026-11-16T00:00:00+00:00")
    assert parsed is not None
    row = parsed.paper
    assert row["s2_corpus_id"] == 195825219 and row["doi"] == FULL
    assert row["dblp_key"] == "conf/dcfs/Freund19"
    assert row["has_abstract"] and row["has_embedding"] and row["n_references"] == 5
    assert parsed.abstract and parsed.abstract.startswith("Since more than five decades")
    assert parsed.vector is not None and len(parsed.vector) == store.DIM
    assert len(parsed.references) == 5
    assert {r["citing_corpus_id"] for r in parsed.references} == {195825219}
    assert all(isinstance(r["cited_corpus_id"], int) for r in parsed.references)
    assert row["parser_version"] == s2.PARSER_VERSION


def test_parse_item_without_abstract_and_with_a_null_reference_list():
    parsed = s2.parse_item(ANSWER_BY_DOI[TITLE_ONLY])
    assert parsed is not None
    assert parsed.abstract is None and not parsed.paper["has_abstract"]
    assert parsed.paper["n_references"] is None and parsed.references == []  # null, not "zero"
    assert parsed.vector is not None and parsed.paper["tldr"]


def test_parse_item_without_a_vector():
    parsed = s2.parse_item(ANSWER_BY_DOI[NO_VECTOR])
    assert parsed is not None and parsed.vector is None and not parsed.paper["has_embedding"]


def test_a_vector_of_the_wrong_size_or_model_is_dropped_and_counted():
    item = json.loads(json.dumps(ANSWER_BY_DOI[FULL]))
    item["embedding"]["vector"] = item["embedding"]["vector"][:10]
    bad = s2.parse_item(item)
    assert bad is not None and bad.vector is None and bad.bad_vector
    item["embedding"] = {"model": "specter@v0.1.1", "vector": [0.0] * store.DIM}
    other = s2.parse_item(item)
    assert other is not None and other.vector is None and not other.bad_vector


def test_an_item_without_a_corpus_id_is_skipped():
    assert s2.parse_item({"paperId": "x", "title": "No corpus id"}) is None


# -- title matching ------------------------------------------------------------------------------


def candidates(match: dict) -> list[dict]:
    return s2._candidates(match["answer"])


def test_a_title_hit_is_accepted_with_a_high_score():
    item, score = s2.best_title_match(match_paper(HIT), candidates(HIT))
    assert item is not None and score >= oa.TITLE_MATCH_MIN


def test_a_longer_title_from_another_year_is_rejected():
    item, _score = s2.best_title_match(match_paper(REJECTED), candidates(REJECTED))
    assert item is None  # the only candidate is seven years away


def test_a_similar_but_different_title_in_the_right_year_is_rejected_but_scored():
    other = [{"title": "On Descriptional Complexity of Some Other Grammars", "year": 2001}]
    item, score = s2.best_title_match(match_paper(REJECTED), other)
    assert item is None and 0 < score < oa.TITLE_MATCH_MIN


def test_a_hit_in_a_year_outside_the_slack_is_rejected():
    far = paper("k", doi=None, title=HIT["query_title"], year=HIT["year"] + 5)
    assert s2.best_title_match(far, candidates(HIT))[0] is None


def test_a_cached_404_has_no_candidates():
    assert NONE["answer"] is None and s2._candidates(None) == []


# -- a fake Semantic Scholar for the harvest tests -----------------------------------------------


def serve_s2(httpx_mock):
    """Answer like the API: the batch endpoint returns one item or null per asked ID, in order;
    the match endpoint returns the fixture match for the title or 404."""
    calls = {"batch": 0, "match": 0, "batch_sizes": []}

    def answer(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            calls["batch"] += 1
            ids = json.loads(request.content)["ids"]
            calls["batch_sizes"].append(len(ids))
            out = [ANSWER_BY_DOI.get(i.removeprefix("DOI:")) for i in ids]
            return httpx.Response(200, json=out)
        calls["match"] += 1
        title = parse_qs(request.url.query.decode())["query"][0]
        for m in MATCHES:
            if m["query_title"] == title and m["answer"] is not None:
                return httpx.Response(200, json=m["answer"])
        return httpx.Response(404, json={"error": "Title match not found"})

    httpx_mock.add_callback(answer, is_reusable=True, is_optional=True)
    return calls


@pytest.fixture
def con(settings):
    connection = connect(settings.paths)
    yield connection
    connection.close()


def pilot_papers() -> list[oa.PaperRef]:
    return [
        paper("conf/x/full", doi=FULL, title="Full record", year=2019),
        paper("conf/x/title-only", doi=TITLE_ONLY, title="Title only record", year=2005),
        paper("conf/x/no-vector", doi=NO_VECTOR, title="No vector record", year=2021),
        paper("conf/x/gone", doi=GONE_1, title="Gone from S2", year=2002),  # null, then no match
        paper("conf/x/hit", doi=None, title=HIT["query_title"], year=HIT["year"]),
        paper("conf/x/rejected", doi=None, title=REJECTED["query_title"], year=REJECTED["year"]),
        paper("conf/x/none", doi=None, title=NONE["query_title"], year=NONE["year"]),
    ]


def test_harvest_then_parse_joins_answers_to_papers(settings, con, httpx_mock):
    calls = serve_s2(httpx_mock)
    c = client(settings, FakeClock())
    papers = pilot_papers()

    stats = s2.harvest(con, c, papers)
    assert calls["batch"] == 1 and calls["batch_sizes"] == [4]  # four DOIs, one batch
    assert calls["match"] == 4  # `gone` (DOI null) and the three without a DOI
    assert stats.batches == 1 and stats.items_returned == 3 and stats.matches == 4

    parsed = s2.parse_s2(c, papers)
    rows = {r["dblp_key"]: r for r in parsed.lookup}
    assert rows["conf/x/full"]["status"] == "matched" and rows["conf/x/full"]["method"] == "doi"
    assert rows["conf/x/full"]["s2_corpus_id"] == 195825219
    assert rows["conf/x/hit"]["method"] == "title" and rows["conf/x/hit"]["s2_corpus_id"]
    assert rows["conf/x/hit"]["title_similarity"] >= oa.TITLE_MATCH_MIN
    for key in ("conf/x/gone", "conf/x/rejected", "conf/x/none"):
        assert rows[key]["status"] == "not_found" and rows[key]["s2_corpus_id"] is None
    assert parsed.stats["matched"] == 4 and parsed.stats["matched_doi"] == 3
    assert parsed.stats["not_found"] == 3 and parsed.stats["not_fetched"] == 0

    assert {a["dblp_key"] for a in parsed.abstracts} == {"conf/x/full"}
    assert parsed.abstracts[0]["source"] == "s2" and parsed.abstracts[0]["n_chars"] > 100
    vectors = {e["dblp_key"]: e for e in parsed.embeddings}
    assert set(vectors) >= {"conf/x/full", "conf/x/title-only"}
    assert "conf/x/no-vector" not in vectors and all(e["source"] == "s2" for e in vectors.values())
    assert parsed.stats["references"] == 5  # only FULL has a reference list
    assert len(parsed.papers) == parsed.stats["s2_papers"] == 4


def test_title_match_runs_only_for_papers_the_doi_batch_did_not_return(settings, con, httpx_mock):
    calls = serve_s2(httpx_mock)
    s2.harvest(con, client(settings, FakeClock()), [paper("k", doi=FULL, year=2019)])
    assert calls == {"batch": 1, "match": 0, "batch_sizes": [1]}


def test_the_cap_leaves_papers_not_fetched_instead_of_not_found(settings, con, httpx_mock):
    serve_s2(httpx_mock)
    c = client(settings, FakeClock())
    papers = pilot_papers()
    stats = s2.harvest(con, c, papers, max_title_matches=2)
    assert stats.matches == 2 and stats.papers_not_matched_by_cap == 2
    rows = {r["dblp_key"]: r["status"] for r in s2.parse_s2(c, papers).lookup}
    # key order: gone, hit, none, rejected; the first two were asked
    assert rows["conf/x/gone"] == "not_found" and rows["conf/x/hit"] == "matched"
    assert rows["conf/x/none"] == "not_fetched" and rows["conf/x/rejected"] == "not_fetched"


def test_a_limit_run_then_a_full_run_needs_no_bookkeeping(settings, con, httpx_mock):
    calls = serve_s2(httpx_mock)
    c = client(settings, FakeClock())
    papers = pilot_papers()
    s2.harvest(con, c, papers[:1])  # a --limit run: only `full` was asked
    rows = {r["dblp_key"]: r["status"] for r in s2.parse_s2(c, papers).lookup}
    assert rows["conf/x/full"] == "matched" and rows["conf/x/title-only"] == "not_fetched"
    s2.harvest(con, c, papers)
    rows = {r["dblp_key"]: r["status"] for r in s2.parse_s2(c, papers).lookup}
    assert "not_fetched" not in rows.values()
    assert calls["batch"] == 2


def test_parse_does_not_touch_the_network(settings, con, httpx_mock):
    serve_s2(httpx_mock)
    c = client(settings, FakeClock())
    papers = pilot_papers()
    s2.harvest(con, c, papers)
    before = len(httpx_mock.get_requests())
    s2.parse_s2(c, papers)
    s2.parse_s2(c, papers)
    assert len(httpx_mock.get_requests()) == before


def test_a_finished_harvest_is_a_no_op_and_restart_asks_the_cache(settings, con, httpx_mock):
    calls = serve_s2(httpx_mock)
    c = client(settings, FakeClock())
    papers = pilot_papers()
    s2.harvest(con, c, papers)
    before = dict(calls)
    again = s2.harvest(con, c, papers)
    assert calls == before and again.batches == 0 and again.matches == 0
    again = s2.harvest(con, c, papers, restart=True)
    assert again.batches == 1 and again.batches_from_cache == 1
    assert again.matches_from_cache == again.matches == 4
    assert calls == before  # everything came from the cache


def test_a_batch_is_split_at_the_configured_size(settings, con, httpx_mock):
    calls = serve_s2(httpx_mock)
    small = settings.sources["semanticscholar"].model_copy(update={"batch_size": 2})
    settings.sources["semanticscholar"] = small
    s2.harvest(con, client(settings, FakeClock()), pilot_papers()[:4])
    assert calls["batch_sizes"] == [2, 2]


def test_older_probes_with_another_field_list_are_ignored(settings, con, httpx_mock):
    serve_s2(httpx_mock)
    c = client(settings, FakeClock())
    c.post(s2.BATCH_PATH, {"ids": [f"DOI:{FULL}"]}, {"fields": "corpusId"})  # a probe
    assert s2.read_cached_answers(c).by_doi == {}
    s2.harvest(con, c, [paper("k", doi=FULL, year=2019)])
    assert set(s2.read_cached_answers(c).by_doi) == {FULL}


def test_parse_before_any_harvest_marks_everything_not_fetched(settings):
    c = client(settings, FakeClock())
    parsed = s2.parse_s2(c, pilot_papers())
    assert parsed.stats["not_fetched"] == len(pilot_papers()) and parsed.stats["matched"] == 0
    assert parsed.embeddings == [] and parsed.abstracts == []


def test_the_newest_answer_wins_when_a_doi_was_asked_twice(settings, httpx_mock):
    httpx_mock.add_response(method="POST", json=[None, None])
    httpx_mock.add_response(method="POST", json=[ANSWER_BY_DOI[FULL]])
    clock = FakeClock()
    c = client(settings, clock)
    c.post(s2.BATCH_PATH, {"ids": [f"DOI:{FULL}", "DOI:10.1/other"]}, s2.batch_params())
    assert s2.read_cached_answers(c).item(FULL) is None
    clock.advance(days=1)
    c.post(s2.BATCH_PATH, {"ids": [f"DOI:{FULL}"]}, s2.batch_params())
    answers = s2.read_cached_answers(c)
    assert answers.item(FULL)["corpusId"] == 195825219
    assert answers.asked == {FULL, "10.1/other"} and answers.item("10.1/other") is None


# -- tables --------------------------------------------------------------------------------------


def test_write_tables_round_trip_keeps_other_sources_and_replaces_its_own(
    settings, con, httpx_mock
):
    serve_s2(httpx_mock)
    c = client(settings, FakeClock())
    papers = pilot_papers()
    s2.harvest(con, c, papers)
    parsed = s2.parse_s2(c, papers)
    oa.write_local_abstracts(
        con,
        settings.paths,
        "openalex",
        [
            {
                "dblp_key": "conf/x/hit",
                "openalex_id": "W1",
                "doi": None,
                "source": "openalex",
                "text": "from openalex",
                "n_chars": 13,
            }
        ],
    )
    store.write_source(
        con,
        settings.paths,
        "local",
        [
            {
                "dblp_key": "conf/x/no-vector",
                "model": "m",
                "source": "local",
                "s2_corpus_id": None,
                "input_kind": "title",
                "abstract_source": None,
                "vector": [0.5] * store.DIM,
            }
        ],
    )
    s2.write_tables(con, settings.paths, parsed)
    s2.write_tables(con, settings.paths, parsed)  # twice: replaces, never duplicates

    assert con.execute("SELECT count(*) FROM stg_s2_lookup").fetchone()[0] == len(papers)
    assert con.execute("SELECT count(*) FROM stg_s2_paper").fetchone()[0] == 4
    assert con.execute("SELECT count(*) FROM stg_s2_reference").fetchone()[0] == 5
    sources = dict(con.execute("SELECT source, count(*) FROM local_abstract GROUP BY 1").fetchall())
    assert sources == {"openalex": 1, "s2": 1}
    emb = dict(con.execute("SELECT source, count(*) FROM local_embedding GROUP BY 1").fetchall())
    assert emb == {"s2": 2, "local": 1}  # the local row of another paper survives
    for name in s2.TABLES:
        assert (settings.paths.warehouse / "staging" / f"{name}.parquet").exists()
    assert (settings.paths.warehouse / "local" / "local_embedding.parquet").exists()


def test_the_api_key_is_sent_but_not_in_the_cached_url(settings, con, httpx_mock, monkeypatch):
    monkeypatch.setenv("S2_API_KEY", "s2-key-SECRET-9876")  # gitleaks:allow (fake test value)
    from flatatlas.settings import load_settings

    keyed = load_settings(data_root=settings.paths.root, env_file=None)
    serve_s2(httpx_mock)
    c = client(keyed, FakeClock())
    s2.harvest(con, c, [paper("k", doi=FULL, year=2019)])
    (request,) = httpx_mock.get_requests()
    assert request.headers["x-api-key"] == "s2-key-SECRET-9876"
    for meta in (keyed.paths.raw / "semanticscholar").rglob("*.meta.json"):
        assert "SECRET" not in meta.read_text()


def test_vectors_are_float_768_in_the_warehouse_and_in_parquet(settings, con):
    import pyarrow as pa
    import pyarrow.parquet as pq

    row = {
        "dblp_key": "k",
        "model": "specter_v2",
        "source": "s2",
        "s2_corpus_id": 1,
        "input_kind": None,
        "abstract_source": None,
        "vector": [0.25] * store.DIM,
    }
    store.write_source(con, settings.paths, "s2", [row])
    assert con.execute("SELECT typeof(vector) FROM local_embedding").fetchone()[0] == "FLOAT[768]"
    table = pq.read_table(settings.paths.warehouse / "local" / "local_embedding.parquet")
    assert table.schema.field("vector").type == pa.list_(pa.float32(), store.DIM)
    assert store.read_rows(con)[0]["vector"][:2] == [0.25, 0.25]
