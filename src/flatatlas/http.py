"""The only module that talks to the network (CLAUDE.md rule 8).

``SourceClient(source_name, settings)`` gives one source a disk cache, a token-bucket rate
limit, retries with back-off, a daily budget guard, and keys that never reach logs, errors or the
cache. No other module may import httpx; a test enforces that.

The client is synchronous. The ``concurrency`` setting of the profile is not used yet.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from flatatlas import __version__
from flatatlas.budget import BudgetExhausted, BudgetLedger, SourceError
from flatatlas.log import redact, register_secret
from flatatlas.settings import Settings, SourceConfig

# httpx logs every request URL at INFO, and for OpenAlex the URL carries the key.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

log = logging.getLogger(__name__)

__all__ = [
    "BudgetExhausted",
    "MissingCredentials",
    "Response",
    "SourceClient",
    "SourceError",
    "TokenBucket",
]

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
CACHED_MISSING_STATUSES = frozenset({404, 410})
_KEPT_HEADERS = ("content-type", "etag", "retry-after", "date")
_KEPT_HEADER_PREFIXES = ("x-rate-limit", "x-ratelimit")
_INTERVAL = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smh]?)\s*$")


class MissingCredentials(SourceError):
    """The source needs an API key that is not configured."""


@dataclass(frozen=True)
class Response:
    """A cached or fresh answer. ``data`` is None for a cached 404/410."""

    status: int
    data: Any
    fetched_at: datetime
    from_cache: bool
    url: str  # without any secret


class TokenBucket:
    """``rate`` tokens per second up to ``burst``; ``acquire()`` sleeps until one is free."""

    def __init__(
        self,
        rate: float,
        burst: int,
        *,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self.rate = rate
        self.capacity = float(max(burst, 1))
        self._tokens = self.capacity
        self._clock = clock
        self._sleep = sleep
        self._updated = clock()
        self._blocked_until = 0.0

    def block_for(self, seconds: float) -> None:
        """Hold every request for at least ``seconds`` (back-off, ``Retry-After``)."""
        self._blocked_until = max(self._blocked_until, self._clock() + seconds)

    def lower_rate(self, rate: float) -> None:
        """Slow down to ``rate`` if that is below the current rate; never speed up."""
        if 0 < rate < self.rate:
            self.rate = rate

    def acquire(self) -> None:
        while True:
            now = self._clock()
            if now < self._blocked_until:
                self._sleep(self._blocked_until - now)
                continue
            self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
            self._updated = now
            if self._tokens >= 1 - 1e-9:
                self._tokens -= 1
                return
            self._sleep((1 - self._tokens) / self.rate)


def _parse_interval_seconds(text: str) -> float | None:
    match = _INTERVAL.match(text)
    if not match:
        return None
    value, unit = float(match.group(1)), match.group(2)
    return value * {"": 1, "s": 1, "m": 60, "h": 3600}[unit]


def _sorted_params(params: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key, value in (params or {}).items():
        values = value if isinstance(value, (list, tuple)) else [value]
        pairs.extend((str(key), str(v)) for v in values)
    return sorted(pairs)


class SourceClient:
    """Cached, rate-limited, retrying, budget-aware client for one source."""

    def __init__(
        self,
        source_name: str,
        settings: Settings,
        *,
        refresh_older_than: timedelta | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if source_name not in settings.sources:
            raise KeyError(f"Unknown source {source_name!r}; see config/sources.yaml")
        self.source = source_name
        self.cfg: SourceConfig = settings.sources[source_name]
        self._settings = settings
        self._refresh_older_than = refresh_older_than
        self._sleep = sleep
        self._now = now
        self.cache_dir = settings.paths.raw / source_name
        self.bucket = TokenBucket(
            self.cfg.requests_per_second, self.cfg.burst, clock=clock, sleep=sleep
        )
        self.ledger = BudgetLedger(
            self.cache_dir / "_budget.json",
            self.cfg.daily_budget_usd,
            now=now,
            source=source_name,
        )
        secret = settings.secret_for(source_name)
        if secret:
            register_secret(secret)
        self._http = httpx.Client(timeout=self.cfg.timeout_seconds, follow_redirects=True)

    # -- public API ---------------------------------------------------------------------------

    def get(
        self, path: str, params: Mapping[str, Any] | None = None, *, cost: str = "list"
    ) -> Response:
        return self.request("GET", path, params=params, cost=cost)

    def post(
        self,
        path: str,
        json_body: Any,
        params: Mapping[str, Any] | None = None,
        *,
        cost: str = "list",
    ) -> Response:
        return self.request("POST", path, params=params, json_body=json_body, cost=cost)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        cost: str = "list",
    ) -> Response:
        """Return the cached answer, or fetch (rate-limited, charged, retried) and cache it.

        ``cost`` names an entry of the source's ``costs`` table (OpenAlex: ``list``,
        ``singleton``, ``search``); it is ignored for sources without a budget.
        """
        method = method.upper()
        url = self._url(path)
        pairs = _sorted_params(params)
        key = self._cache_key(method, url, pairs, json_body)
        shown_url = f"{url}?{urlencode(pairs)}" if pairs else url

        cached = self._read_cache(key, shown_url)
        if cached is not None:
            return cached

        cost_usd = self._cost(cost)
        send_params, headers = self._auth_and_identity(pairs)

        attempt = 0
        while True:
            attempt += 1
            self.bucket.acquire()
            self.ledger.charge(cost_usd)
            try:
                resp = self._http.request(
                    method, url, params=send_params, json=json_body, headers=headers
                )
            except httpx.TransportError as exc:
                if attempt >= self.cfg.max_attempts:
                    raise SourceError(
                        redact(
                            f"{self.source}: {type(exc).__name__} after {attempt} attempts "
                            f"for {shown_url}"
                        )
                    ) from None
                delay = self._backoff(attempt)
                log.warning(
                    "%s: %s, retrying in %.1fs (attempt %d)",
                    self.source, type(exc).__name__, delay, attempt,
                )  # fmt: skip
                self.bucket.block_for(delay)
                continue

            self._adapt_to_headers(resp.headers)
            status = resp.status_code
            if status in RETRY_STATUSES:
                if attempt >= self.cfg.max_attempts:
                    raise SourceError(
                        f"{self.source}: HTTP {status} after {attempt} attempts for {shown_url}"
                    )
                delay = self._retry_delay(resp, attempt, shown_url)
                log.warning(
                    "%s: HTTP %d, retrying in %.1fs (attempt %d)",
                    self.source,
                    status,
                    delay,
                    attempt,
                )
                self.bucket.block_for(delay)
                continue
            if status == 200:
                try:
                    data = resp.json()
                except ValueError:
                    raise SourceError(
                        f"{self.source}: HTTP 200 but the body is not JSON for {shown_url}"
                    ) from None
                return self._write_cache(key, method, shown_url, status, data, resp.headers, cost)
            if status in CACHED_MISSING_STATUSES:
                return self._write_cache(key, method, shown_url, status, None, resp.headers, cost)
            raise SourceError(f"{self.source}: HTTP {status} for {shown_url}")

    def cached(self, path: str, params: Mapping[str, Any] | None = None) -> Response | None:
        """The cached answer to a GET, or None. Never touches the network (used by parse stages)."""
        url = self._url(path)
        pairs = _sorted_params(params)
        key = self._cache_key("GET", url, pairs, None)
        shown_url = f"{url}?{urlencode(pairs)}" if pairs else url
        return self._read_cache(key, shown_url)

    def iter_cached(self, url_prefix: str = "") -> Iterator[Response]:
        """Every cached answer whose URL starts with ``url_prefix`` (relative to the base URL).

        Order follows the file names, so it is stable but meaningless. Corrupt entries are skipped.
        """
        prefix = self._url(url_prefix) if url_prefix else self.cfg.base_url.rstrip("/")
        for meta_path in sorted(self.cache_dir.glob("??/*.meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if not str(meta["url"]).startswith(prefix):
                    continue
                data_path = meta_path.with_name(
                    meta_path.name.removesuffix(".meta.json") + ".json.gz"
                )
                data = json.loads(gzip.decompress(data_path.read_bytes()))
                fetched_at = datetime.fromisoformat(meta["fetched_at"])
                yield Response(int(meta["status"]), data, fetched_at, True, str(meta["url"]))
            except (OSError, ValueError, KeyError, EOFError):
                continue

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> SourceClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- request building ---------------------------------------------------------------------

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.cfg.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _cost(self, kind: str) -> float:
        if self.cfg.daily_budget_usd is None:
            return 0.0
        try:
            return self.cfg.costs[kind]
        except KeyError:
            known = ", ".join(sorted(self.cfg.costs)) or "none"
            raise ValueError(
                f"{self.source}: unknown cost kind {kind!r} (known: {known})"
            ) from None

    def _auth_and_identity(
        self, pairs: list[tuple[str, str]]
    ) -> tuple[list[tuple[str, str]], dict[str, str]]:
        """Params and headers to send. Secrets and the email are added here, after the cache key."""
        auth = self.cfg.auth
        secret = self._settings.secret_for(self.source)
        if auth.style != "none" and auth.required and not secret:
            raise MissingCredentials(
                f"{self.source}: no API key configured (set {str(auth.secret).upper()} in .env)"
            )
        email = self._settings.contact_email
        agent = f"FLATAtlas/{__version__} (https://github.com/gmcmduarte/flat-atlas"
        agent += f"; mailto:{email})" if email else ")"
        headers = {"User-Agent": agent, "Accept": "application/json"}
        send = list(pairs)
        if self.cfg.mailto_param and email:
            send.append((self.cfg.mailto_param, email))
        if secret and auth.name:
            if auth.style == "query":
                send.append((auth.name, secret))
            elif auth.style == "header":
                headers[auth.name] = secret
        return send, headers

    # -- retry and rate-limit policy ----------------------------------------------------------

    def _backoff(self, attempt: int) -> float:
        return min(self.cfg.max_backoff_seconds, 2.0 ** (attempt - 1))

    def _retry_delay(self, resp: httpx.Response, attempt: int, shown_url: str) -> float:
        wait = self._retry_after(resp.headers.get("retry-after"))
        if wait is None:
            return self._backoff(attempt)
        if wait > self.cfg.max_retry_wait_seconds:
            raise SourceError(
                f"{self.source}: asked to wait {wait:.0f}s (limit "
                f"{self.cfg.max_retry_wait_seconds:.0f}s) for {shown_url}; try again later"
            )
        return wait

    def _retry_after(self, value: str | None) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            pass
        try:
            return max(0.0, (parsedate_to_datetime(value) - self._now()).total_seconds())
        except (TypeError, ValueError):
            return None

    def _adapt_to_headers(self, headers: httpx.Headers) -> None:
        """Crossref publishes ``x-rate-limit-limit: 50`` and ``x-rate-limit-interval: 1s``."""
        limit, interval = headers.get("x-rate-limit-limit"), headers.get("x-rate-limit-interval")
        if not limit or not interval:
            return
        seconds = _parse_interval_seconds(interval)
        try:
            count = float(limit)
        except ValueError:
            return
        if seconds and count > 0:
            self.bucket.lower_rate(count / seconds)

    # -- cache --------------------------------------------------------------------------------

    @staticmethod
    def _cache_key(method: str, url: str, pairs: list[tuple[str, str]], body: Any) -> str:
        blob = json.dumps([method, url, pairs, body], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()

    def _cache_paths(self, key: str) -> tuple[Path, Path]:
        folder = self.cache_dir / key[:2]
        return folder / f"{key}.json.gz", folder / f"{key}.meta.json"

    def _read_cache(self, key: str, shown_url: str) -> Response | None:
        data_path, meta_path = self._cache_paths(key)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(meta["fetched_at"])
            if (
                self._refresh_older_than is not None
                and self._now() - fetched_at > self._refresh_older_than
            ):
                return None
            data = json.loads(gzip.decompress(data_path.read_bytes()))
            return Response(int(meta["status"]), data, fetched_at, True, shown_url)
        except (OSError, ValueError, KeyError, EOFError):  # missing or corrupt: refetch
            return None

    def _write_cache(
        self,
        key: str,
        method: str,
        shown_url: str,
        status: int,
        data: Any,
        headers: httpx.Headers,
        cost: str,
    ) -> Response:
        fetched_at = self._now()
        data_path, meta_path = self._cache_paths(key)
        data_path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "source": self.source,
            "method": method,
            "url": shown_url,
            "status": status,
            "fetched_at": fetched_at.isoformat(),
            "cost_kind": cost,
            "headers": {
                k: v
                for k, v in headers.items()
                if k.lower() in _KEPT_HEADERS or k.lower().startswith(_KEPT_HEADER_PREFIXES)
            },
        }
        payload = gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0)
        # Data first, metadata last: a reader needs both, so a crash in between is just a miss.
        self._atomic_write(data_path, payload)
        self._atomic_write(meta_path, json.dumps(meta, indent=1).encode())
        return Response(status, data, fetched_at, False, shown_url)

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_bytes(payload)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
