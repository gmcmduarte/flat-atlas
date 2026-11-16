import gzip
import json
import logging
import re
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from flatatlas import log as flog
from flatatlas.http import BudgetExhausted, MissingCredentials, SourceClient, SourceError
from flatatlas.settings import Settings
from helpers import FAKE_EMAIL, FAKE_OPENALEX_KEY, FakeClock

DBLP = "https://dblp.org/search/publ/api"


def client(source: str, settings: Settings, clock: FakeClock, **kwargs) -> SourceClient:
    return SourceClient(
        source, settings, clock=clock.monotonic, sleep=clock.sleep, now=clock.now, **kwargs
    )


def cached_files(settings: Settings, source: str) -> list[Path]:
    return [p for p in (settings.paths.raw / source).rglob("*") if p.is_file()]


# -- cache ------------------------------------------------------------------------------------


def test_cache_hit_makes_zero_requests(settings, clock, httpx_mock):
    httpx_mock.add_response(url=f"{DBLP}?q=automata&h=5", json={"hits": 5})
    c = client("dblp", settings, clock)
    first = c.get("search/publ/api", {"q": "automata", "h": 5})
    assert (first.data, first.from_cache) == ({"hits": 5}, False)

    # Same request: different param order and a new client (as after a restart).
    again = client("dblp", settings, clock).get("search/publ/api", {"h": 5, "q": "automata"})
    assert (again.data, again.from_cache) == ({"hits": 5}, True)
    assert len(httpx_mock.get_requests()) == 1


def test_cache_files_are_gzip_json_plus_metadata(settings, clock, httpx_mock):
    httpx_mock.add_response(json={"x": [1, 2]}, headers={"x-rate-limit-limit": "50"})
    client("dblp", settings, clock).get(f"{DBLP}", {"q": "a"})
    files = cached_files(settings, "dblp")
    data = next(f for f in files if f.name.endswith(".json.gz"))
    meta = json.loads(next(f for f in files if f.name.endswith(".meta.json")).read_text())
    assert json.loads(gzip.decompress(data.read_bytes())) == {"x": [1, 2]}
    assert meta["status"] == 200 and meta["source"] == "dblp"
    assert meta["url"] == f"{DBLP}?q=a"
    assert meta["headers"]["x-rate-limit-limit"] == "50"


def test_different_params_or_body_do_not_share_a_cache_entry(settings, clock, httpx_mock):
    httpx_mock.add_response(method="GET", json={"n": 1})
    httpx_mock.add_response(method="GET", json={"n": 2})
    httpx_mock.add_response(method="POST", json={"n": 3})
    httpx_mock.add_response(method="POST", json={"n": 4})
    c = client("semanticscholar", settings, clock)
    assert c.get("paper/x", {"fields": "title"}).data == {"n": 1}
    assert c.get("paper/x", {"fields": "title,year"}).data == {"n": 2}
    assert c.post("paper/batch", {"ids": ["a"]}).data == {"n": 3}
    assert c.post("paper/batch", {"ids": ["b"]}).data == {"n": 4}
    assert c.post("paper/batch", {"ids": ["a"]}).from_cache


def test_post_body_is_kept_with_the_cached_answer(settings, clock, httpx_mock):
    httpx_mock.add_response(method="POST", json=[{"corpusId": 1}, None])
    c = client("semanticscholar", settings, clock)
    body = {"ids": ["DOI:10.1/a", "DOI:10.1/b"]}
    fresh = c.post("paper/batch", body)
    assert fresh.request_body == body
    (again,) = list(client("semanticscholar", settings, clock).iter_cached("paper/batch"))
    assert again.request_body == body and again.data == [{"corpusId": 1}, None]
    assert c.post("paper/batch", body).request_body == body  # a cache hit carries it too


def test_get_answers_have_no_request_body(settings, clock, httpx_mock):
    httpx_mock.add_response(json={"x": 1})
    c = client("dblp", settings, clock)
    assert c.get(DBLP, {"q": "a"}).request_body is None
    assert c.get(DBLP, {"q": "a"}).request_body is None


def test_refresh_older_than_refetches_old_entries(settings, clock, httpx_mock):
    httpx_mock.add_response(json={"v": 1})
    httpx_mock.add_response(json={"v": 2})
    client("dblp", settings, clock).get(DBLP, {"q": "a"})
    clock.advance(days=10)
    young = client("dblp", settings, clock, refresh_older_than=timedelta(days=30))
    assert young.get(DBLP, {"q": "a"}).data == {"v": 1}  # 10 days old: kept
    clock.advance(days=25)
    assert young.get(DBLP, {"q": "a"}).data == {"v": 2}  # 35 days old: refreshed
    assert len(httpx_mock.get_requests()) == 2


def test_corrupt_cache_entry_is_refetched(settings, clock, httpx_mock):
    httpx_mock.add_response(json={"v": 1})
    httpx_mock.add_response(json={"v": 2})
    client("dblp", settings, clock).get(DBLP, {"q": "a"})
    next(f for f in cached_files(settings, "dblp") if f.name.endswith(".json.gz")).write_bytes(b"x")
    assert client("dblp", settings, clock).get(DBLP, {"q": "a"}).data == {"v": 2}


def test_404_is_cached_other_client_errors_raise(settings, clock, httpx_mock):
    httpx_mock.add_response(status_code=404)
    httpx_mock.add_response(status_code=403)
    c = client("dblp", settings, clock)
    missing = c.get(DBLP, {"q": "a"})
    assert (missing.status, missing.data) == (404, None)
    assert c.get(DBLP, {"q": "a"}).from_cache
    with pytest.raises(SourceError, match="HTTP 403"):
        c.get(DBLP, {"q": "b"})
    assert len(httpx_mock.get_requests()) == 2


# -- retry and rate limit ---------------------------------------------------------------------


def test_429_with_retry_after_waits_then_succeeds(settings, clock, httpx_mock):
    httpx_mock.add_response(status_code=429, headers={"Retry-After": "2"})
    httpx_mock.add_response(json={"ok": True})
    result = client("dblp", settings, clock).get(DBLP, {"q": "a"})
    assert result.data == {"ok": True}
    assert sum(clock.slept) >= 2.0
    assert len(httpx_mock.get_requests()) == 2


def test_5xx_backs_off_exponentially_then_gives_up(settings, clock, httpx_mock):
    for _ in range(settings.sources["dblp"].max_attempts):
        httpx_mock.add_response(status_code=503)
    with pytest.raises(SourceError, match="HTTP 503 after 6 attempts"):
        client("dblp", settings, clock).get(DBLP, {"q": "a"})
    # 1s rate limit between requests is hidden inside the waits: 1, 2, 4, 8, 16 back-off.
    assert sum(clock.slept) >= 1 + 2 + 4 + 8 + 16


def test_retry_after_as_http_date(settings, clock, httpx_mock):
    httpx_mock.add_response(
        status_code=429, headers={"Retry-After": "Sun, 15 Nov 2026 12:00:07 GMT"}
    )
    httpx_mock.add_response(json={})
    client("dblp", settings, clock).get(DBLP)
    assert sum(clock.slept) >= 7.0


def test_absurd_retry_after_is_refused(settings, clock, httpx_mock):
    httpx_mock.add_response(status_code=429, headers={"Retry-After": "86400"})
    with pytest.raises(SourceError, match="asked to wait 86400s"):
        client("dblp", settings, clock).get(DBLP)
    assert sum(clock.slept) < 5


def test_network_errors_are_retried(settings, clock, httpx_mock):
    httpx_mock.add_exception(httpx.ConnectTimeout("timed out"))
    httpx_mock.add_response(json={"ok": 1})
    assert client("dblp", settings, clock).get(DBLP).data == {"ok": 1}


def test_requests_are_spaced_by_the_rate_limit(settings, clock, httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(json={})
    c = client("dblp", settings, clock)  # 1 request/s, burst 1
    start = clock.monotonic()
    for q in "abc":
        c.get(DBLP, {"q": q})
    assert clock.monotonic() - start >= 2.0 - 1e-6


def test_crossref_rate_limit_headers_slow_the_client_down(settings, clock, httpx_mock):
    httpx_mock.add_response(
        json={}, headers={"x-rate-limit-limit": "1", "x-rate-limit-interval": "2s"}
    )
    c = client("crossref", settings, clock)
    c.get("works/10.1/x")
    assert c.bucket.rate == pytest.approx(0.5)  # was 3/s


# -- identity, keys and budget -----------------------------------------------------------------


def test_identity_and_auth_are_sent_but_not_cached(settings, clock, httpx_mock):
    httpx_mock.add_response(json={})
    httpx_mock.add_response(json={})
    client("openalex", settings, clock).get("works", {"filter": "doi:x"}, cost="singleton")
    request = httpx_mock.get_requests()[0]
    assert request.url.params["api_key"] == FAKE_OPENALEX_KEY
    assert FAKE_EMAIL in request.headers["user-agent"]
    assert request.headers["user-agent"].startswith("FLATAtlas/")

    client("crossref", settings, clock).get("works/10.1/x")
    assert httpx_mock.get_requests()[1].url.params["mailto"] == FAKE_EMAIL

    # The cache key does not depend on the key, and nothing on disk contains it.
    for f in cached_files(settings, "openalex"):
        raw = f.read_bytes()
        if f.name.endswith(".json.gz"):
            raw = gzip.decompress(raw)
        assert FAKE_OPENALEX_KEY.encode() not in raw


def test_s2_key_goes_in_a_header(settings, clock, httpx_mock, monkeypatch):
    monkeypatch.setenv("S2_API_KEY", "s2-key-ABCDEFGH")  # gitleaks:allow
    from flatatlas.settings import load_settings

    s = load_settings(data_root=settings.paths.root, env_file=None)
    httpx_mock.add_response(json={})
    client("semanticscholar", s, clock).get("paper/x")
    assert httpx_mock.get_requests()[0].headers["x-api-key"] == "s2-key-ABCDEFGH"


def test_missing_required_key_raises_before_any_request(settings, clock, monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEY")
    from flatatlas.settings import load_settings

    s = load_settings(data_root=settings.paths.root, env_file=None)
    with pytest.raises(MissingCredentials, match="OPENALEX_API_KEY"):
        client("openalex", s, clock).get("works")


def test_api_key_never_appears_in_logs_errors_or_files(
    settings, clock, httpx_mock, caplog, tmp_path
):
    caplog.set_level(logging.DEBUG)
    log_file = flog.setup_logging(tmp_path / "logs", level=logging.DEBUG)
    max_attempts = settings.sources["openalex"].max_attempts
    httpx_mock.add_response(json={"ok": 1})  # a: fine
    httpx_mock.add_response(status_code=503)  # b: 503, a connection error that echoes the key, 500s
    httpx_mock.add_exception(httpx.ConnectError(f"cannot reach host?api_key={FAKE_OPENALEX_KEY}"))
    for _ in range(max_attempts - 2):
        httpx_mock.add_response(status_code=500)
    httpx_mock.add_response(status_code=403)  # c: not retried

    c = client("openalex", settings, clock)
    c.get("works", {"filter": "a"}, cost="singleton")
    errors = []
    for name in "bc":
        with pytest.raises(SourceError) as excinfo:
            c.get("works", {"filter": name}, cost="singleton")
        errors.append(excinfo.value)
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert [str(e)[:30] for e in errors] == [
        "openalex: HTTP 500 after 6 att",
        "openalex: HTTP 403 for https:/",
    ]
    assert FAKE_OPENALEX_KEY not in caplog.text
    assert FAKE_OPENALEX_KEY not in log_file.read_text()
    for error in errors:
        assert FAKE_OPENALEX_KEY not in str(error)
        assert FAKE_OPENALEX_KEY not in repr(error)
    for f in cached_files(settings, "openalex"):
        assert FAKE_OPENALEX_KEY.encode() not in f.read_bytes()
    flog.setup_logging(None)  # drop handlers that point into tmp_path


def test_transport_error_text_is_redacted_and_not_chained(settings, clock, httpx_mock):
    max_attempts = settings.sources["openalex"].max_attempts
    for _ in range(max_attempts):
        httpx_mock.add_exception(httpx.ConnectError(f"boom api_key={FAKE_OPENALEX_KEY}"))
    with pytest.raises(SourceError) as excinfo:
        client("openalex", settings, clock).get("works", cost="singleton")
    assert FAKE_OPENALEX_KEY not in str(excinfo.value)
    assert excinfo.value.__cause__ is None and excinfo.value.__suppress_context__


def test_redacting_formatter_hides_keys_in_tracebacks(settings):
    flog.register_secret(FAKE_OPENALEX_KEY)
    try:
        raise ValueError(f"bad url ?api_key={FAKE_OPENALEX_KEY}")
    except ValueError:
        record = logging.LogRecord(
            "x", logging.ERROR, __file__, 1, "failed", None, __import__("sys").exc_info()
        )
    text = flog.RedactingFormatter("%(message)s").format(record)
    assert FAKE_OPENALEX_KEY not in text and "***" in text


def test_budget_guard_stops_before_the_limit_and_resumes_next_utc_day(settings, clock, httpx_mock):
    # $1/day at $0.0001 per list call = 10,000 calls. Shrink the budget to 3 calls.
    settings.sources["openalex"] = settings.sources["openalex"].model_copy(
        update={"daily_budget_usd": 0.0003}
    )
    for _ in range(4):
        httpx_mock.add_response(json={})
    c = client("openalex", settings, clock)
    for n in range(3):
        c.get("works", {"page": n})
    assert c.ledger.spent_today_usd() == pytest.approx(0.0003)

    with pytest.raises(BudgetExhausted, match="midnight UTC"):
        c.get("works", {"page": 3})
    assert len(httpx_mock.get_requests()) == 3  # the fourth call was never sent

    # Singleton lookups are free and cached calls cost nothing, even when the budget is spent.
    assert c.get("works", {"page": 0}).from_cache

    # A new process the same day still sees the spend.
    with pytest.raises(BudgetExhausted):
        client("openalex", settings, clock).get("works", {"page": 3})

    clock.advance(hours=12)  # 12:00 UTC + 12h = next day 00:00 UTC
    assert client("openalex", settings, clock).get("works", {"page": 3}).data == {}


def test_free_calls_do_not_consume_budget(settings, clock, httpx_mock):
    httpx_mock.add_response(json={})
    c = client("openalex", settings, clock)
    c.get("works/doi:10.1/x", cost="singleton")
    assert c.ledger.spent_today_usd() == 0


def test_unknown_cost_kind_is_an_error(settings, clock):
    with pytest.raises(ValueError, match="unknown cost kind"):
        client("openalex", settings, clock).get("works", cost="bulk")


# -- architecture rule ------------------------------------------------------------------------


def test_only_http_module_imports_httpx():
    src = Path(__file__).resolve().parents[2] / "src" / "flatatlas"
    pattern = re.compile(r"^\s*(import httpx|from httpx\b)", re.MULTILINE)
    offenders = [
        p.relative_to(src).as_posix()
        for p in src.rglob("*.py")
        if p.name != "http.py" and pattern.search(p.read_text())
    ]
    assert offenders == []


# -- read-only cache access (parse stages) ------------------------------------------------------


def test_cached_returns_the_stored_answer_without_the_network(settings, clock, httpx_mock):
    httpx_mock.add_response(json={"hits": 5})
    c = client("dblp", settings, clock)
    assert c.cached("search/publ/api", {"q": "automata"}) is None  # nothing stored yet
    c.get("search/publ/api", {"q": "automata"})
    hit = c.cached("search/publ/api", {"q": "automata"})
    assert hit is not None and hit.data == {"hits": 5} and hit.from_cache
    assert c.cached("search/publ/api", {"q": "other"}) is None
    assert len(httpx_mock.get_requests()) == 1


def test_iter_cached_lists_answers_by_url_prefix_and_keeps_404s(settings, clock, httpx_mock):
    httpx_mock.add_response(url=f"{DBLP}?q=a", json={"n": 1})
    httpx_mock.add_response(url="https://dblp.org/search/venue/api?q=b", status_code=404)
    c = client("dblp", settings, clock)
    c.get("search/publ/api", {"q": "a"})
    c.get("search/venue/api", {"q": "b"})
    everything = list(c.iter_cached())
    assert sorted(r.status for r in everything) == [200, 404]
    only_publ = list(c.iter_cached("search/publ"))
    assert [(r.url, r.data) for r in only_publ] == [(f"{DBLP}?q=a", {"n": 1})]
    # a corrupt data file is skipped, not fatal
    for path in (settings.paths.raw / "dblp").rglob("*.json.gz"):
        path.write_bytes(b"not gzip")
    assert list(c.iter_cached()) == []
