"""Titles of cited works and of background papers, from OpenAlex (P1-05).

Two harvests share one idea: ask OpenAlex for works by ID (or by filter) with a tiny ``select``,
through ``SourceClient`` (cached, rate-limited, budget-guarded, resumable), and parse the cached
answers offline.

* **Reference titles** (PLAN §9.3, composite text). The warehouse holds the IDs of the works the
  pilot papers cite (``stg_openalex_reference``). Titles of those inside the pilot come from
  ``stg_openalex_work``; the rest (``stg_reference_candidates``) are fetched here, 100 IDs per
  call (``filter=openalex:W1|W2|...``), USD 0.0001 a call.
* **Background titles** (PLAN §9.1 step 2): about 5,000 titles of theory papers that are not
  FLAT, the contrast set for c-TF-IDF. Fetched once with ``config/taxonomy.yaml``'s filter.

Titles are public metadata (CC0) and may be exported later; abstracts are never fetched here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import duckdb
import pyarrow as pa

from flatatlas.db import replace_table
from flatatlas.harvest import Page, paged
from flatatlas.http import SourceClient
from flatatlas.settings import Paths
from flatatlas.sources.openalex import short_id

log = logging.getLogger(__name__)

SOURCE = "openalex"
PARSER_VERSION = "reftitles-parse/1"
SELECT = "id,title,publication_year,type"
ID_FILTER = "openalex"  # filter=openalex:W1|W2 (checked live, docs/notes/sources.md)
TABLE = "stg_reference_title"
BACKGROUND_TABLE = "stg_background_title"

_S = pa.string()
SCHEMA = pa.schema(
    [
        ("openalex_id", _S),
        ("title", _S),
        ("publication_year", pa.int16()),
        ("type", _S),
        ("source", _S),  # pilot | openalex
        ("fetched", pa.bool_()),  # asked and answered (a null title can still be a real answer)
        ("n_citing_pilot_works", pa.int32()),
        ("parser_version", _S),
    ]
)
BACKGROUND_SCHEMA = pa.schema(
    [("openalex_id", _S), ("title", _S), ("publication_year", pa.int16()), ("type", _S)]
)


# -- which IDs --------------------------------------------------------------------------------


def candidate_ids(con: duckdb.DuckDBPyConnection, limit: int | None = None) -> list[str]:
    """Cited works outside the pilot, the most cited by pilot works first (ties by ID)."""
    sql = (
        "SELECT openalex_id FROM stg_reference_candidates "
        "ORDER BY n_citing_pilot_works DESC, openalex_id"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [r[0] for r in con.execute(sql).fetchall()]


def id_batches(ids: Sequence[str], size: int) -> list[list[str]]:
    """Chunks of ``size`` IDs in the given order (the order is the plan; keep it stable)."""
    return [list(ids[i : i + size]) for i in range(0, len(ids), size)]


def batch_params(batch: Sequence[str]) -> dict[str, Any]:
    return {
        "filter": f"{ID_FILTER}:" + "|".join(batch),
        "per_page": len(batch),
        "select": SELECT,
    }


# -- harvest ----------------------------------------------------------------------------------


@dataclass
class HarvestStats:
    batches: int = 0
    batches_from_cache: int = 0
    works_returned: int = 0
    ids_asked: int = 0
    notes: list[str] = field(default_factory=list)

    def as_counts(self) -> dict[str, int]:
        return {
            "id_batches": self.batches,
            "id_batches_from_cache": self.batches_from_cache,
            "works_returned": self.works_returned,
            "ids_asked": self.ids_asked,
        }


def estimate(n_ids: int, batch_size: int, cost_per_call: float, spent: float, budget: float | None):
    """Calls and dollars for ``n_ids`` (cache hits cost nothing; this ignores them)."""
    calls = -(-n_ids // batch_size)
    dollars = calls * cost_per_call
    return {
        "ids": n_ids,
        "calls": calls,
        "usd": round(dollars, 4),
        "spent_today_usd": round(spent, 4),
        "daily_budget_usd": budget,
        "fits_today": budget is None or spent + dollars <= budget,
    }


def harvest_reference_titles(
    con: duckdb.DuckDBPyConnection,
    client: SourceClient,
    ids: Sequence[str],
    *,
    restart: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> HarvestStats:
    """Fetch the titles of ``ids`` in batches. Resumable; raises ``BudgetExhausted`` when the day's
    budget is used up (the cursor is saved)."""
    import hashlib

    stats = HarvestStats(ids_asked=len(ids))
    say = on_progress or (lambda _m: None)
    batches = id_batches(ids, client.cfg.batch_size)
    if not batches:
        return stats
    digest = hashlib.sha1("\n".join(ids).encode()).hexdigest()[:10]  # noqa: S324 - not security
    job = f"reference-titles:{digest}"

    def fetch(cursor: str | None) -> Page:
        index = int(cursor or 0)
        resp = client.get("/works", batch_params(batches[index]))
        stats.batches += 1
        stats.batches_from_cache += resp.from_cache
        results = resp.data["results"]
        stats.works_returned += len(results)
        if (index + 1) % 10 == 0 or index + 1 == len(batches):
            say(
                f"reference titles: batch {index + 1}/{len(batches)} ({stats.works_returned} works)"
            )
        nxt = str(index + 1) if index + 1 < len(batches) else None
        return Page(items=results, next_cursor=nxt)

    for _page in paged(con, SOURCE, job, fetch, restart=restart):
        pass
    return stats


# -- parse ------------------------------------------------------------------------------------


@dataclass
class CachedTitles:
    asked: set[str] = field(default_factory=set)
    works: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)


def read_cached_titles(client: SourceClient) -> CachedTitles:
    """Scan the cache for ID-batch answers of the current ``select``; newest answer wins."""
    out = CachedTitles()
    for resp in client.iter_cached("/works"):
        if resp.status != 200 or not isinstance(resp.data, dict):
            continue
        query = parse_qs(urlparse(resp.url).query)
        if query.get("select") != [SELECT]:
            continue
        flt = (query.get("filter") or [""])[0]
        if not flt.startswith(f"{ID_FILTER}:"):
            continue
        for part in flt[len(ID_FILTER) + 1 :].split("|"):
            wid = short_id(part)
            if wid:
                out.asked.add(wid)
        stamp = resp.fetched_at.isoformat()
        for work in resp.data.get("results") or []:
            wid = short_id(work.get("id"))
            if wid and (wid not in out.works or out.works[wid][0] < stamp):
                out.works[wid] = (stamp, work)
    return out


def build_rows(
    pilot: Sequence[dict[str, Any]],
    candidates: Sequence[dict[str, Any]],
    cached: CachedTitles,
) -> list[dict[str, Any]]:
    """One row per cited work we know something about: the pilot works (titles from
    ``stg_openalex_work``) and every candidate that was asked (title null if OpenAlex has none)."""
    rows: list[dict[str, Any]] = []
    pilot_ids = set()
    for w in pilot:
        pilot_ids.add(w["openalex_id"])
        rows.append(
            {
                "openalex_id": w["openalex_id"],
                "title": w.get("title"),
                "publication_year": w.get("publication_year"),
                "type": w.get("type"),
                "source": "pilot",
                "fetched": True,
                "n_citing_pilot_works": None,
                "parser_version": PARSER_VERSION,
            }
        )
    for cand in candidates:
        wid = cand["openalex_id"]
        if wid in pilot_ids or wid not in cached.asked:
            continue
        work = cached.works.get(wid, (None, {}))[1]
        rows.append(
            {
                "openalex_id": wid,
                "title": (work.get("title") or None),
                "publication_year": work.get("publication_year"),
                "type": work.get("type"),
                "source": "openalex",
                "fetched": True,
                "n_citing_pilot_works": cand["n_citing_pilot_works"],
                "parser_version": PARSER_VERSION,
            }
        )
    return rows


def parse_reference_titles(con: duckdb.DuckDBPyConnection, client: SourceClient) -> dict[str, Any]:
    pilot = [
        dict(zip(("openalex_id", "title", "publication_year", "type"), r, strict=True))
        for r in con.execute(
            "SELECT openalex_id, title, publication_year, type FROM stg_openalex_work "
            "ORDER BY openalex_id"
        ).fetchall()
    ]
    candidates = [
        {"openalex_id": r[0], "n_citing_pilot_works": r[1]}
        for r in con.execute(
            "SELECT openalex_id, n_citing_pilot_works FROM stg_reference_candidates "
            "ORDER BY n_citing_pilot_works DESC, openalex_id"
        ).fetchall()
    ]
    cached = read_cached_titles(client)
    rows = build_rows(pilot, candidates, cached)
    return {"rows": rows, "n_candidates": len(candidates), "n_asked": len(cached.asked)}


def write_reference_titles(
    con: duckdb.DuckDBPyConnection, paths: Paths, rows: Sequence[dict[str, Any]]
) -> None:
    table = pa.Table.from_pylist(list(rows), schema=SCHEMA)
    replace_table(con, TABLE, table, paths.warehouse / "staging" / f"{TABLE}.parquet")


def coverage(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Share of the pilot works' references (edges and distinct cited works) that have a title."""
    edges, with_title = con.execute(
        "SELECT count(*), count(t.title) FROM stg_openalex_reference r "
        "LEFT JOIN stg_reference_title t ON t.openalex_id = r.cited_openalex_id"
    ).fetchone()
    d_all, d_title = con.execute(
        "SELECT count(DISTINCT r.cited_openalex_id), "
        "count(DISTINCT CASE WHEN t.title IS NOT NULL THEN r.cited_openalex_id END) "
        "FROM stg_openalex_reference r "
        "LEFT JOIN stg_reference_title t ON t.openalex_id = r.cited_openalex_id"
    ).fetchone()
    per_work = con.execute(
        "SELECT r.citing_openalex_id, count(*) n, count(t.title) k FROM stg_openalex_reference r "
        "LEFT JOIN stg_reference_title t ON t.openalex_id = r.cited_openalex_id "
        "GROUP BY 1"
    ).fetchall()
    return {
        "edges": edges,
        "edges_with_title": with_title,
        "edge_share": with_title / edges if edges else 0.0,
        "cited_works": d_all,
        "cited_works_with_title": d_title,
        "works_with_references": len(per_work),
        "works_with_10_titles": sum(1 for _, _n, k in per_work if k >= 10),
    }


# -- background titles --------------------------------------------------------------------------


def background_params(filter_: str, n_titles: int, per_page: int, seed: int, page: int):
    """One page of a seeded random sample (OpenAlex ``sample`` pages like a normal list)."""
    return {
        "filter": filter_,
        "sample": n_titles,
        "seed": seed,
        "per_page": per_page,
        "page": page,
        "select": SELECT,
    }


def harvest_background_titles(
    con: duckdb.DuckDBPyConnection,
    client: SourceClient,
    *,
    filter_: str,
    n_titles: int,
    per_page: int,
    seed: int,
    restart: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> HarvestStats:
    """Fetch the sample, ``per_page`` titles per call. Resumable; USD 0.0001 a call."""
    stats = HarvestStats(ids_asked=n_titles)
    say = on_progress or (lambda _m: None)
    n_pages = -(-n_titles // per_page)
    job = f"background-titles:{seed}:{n_titles}:{per_page}"

    def fetch(cursor: str | None) -> Page:
        page = int(cursor or 1)
        resp = client.get("/works", background_params(filter_, n_titles, per_page, seed, page))
        stats.batches += 1
        stats.batches_from_cache += resp.from_cache
        results = resp.data["results"]
        stats.works_returned += len(results)
        say(f"background titles: page {page}/{n_pages} ({stats.works_returned} works)")
        return Page(items=results, next_cursor=str(page + 1) if page < n_pages else None)

    for _page in paged(con, SOURCE, job, fetch, restart=restart):
        pass
    return stats


def parse_background_titles(client: SourceClient, *, filter_: str) -> list[dict[str, Any]]:
    """Titles from the cached sample pages of ``filter_`` (newest answer wins per work)."""
    found: dict[str, tuple[str, dict[str, Any]]] = {}
    for resp in client.iter_cached("/works"):
        if resp.status != 200 or not isinstance(resp.data, dict):
            continue
        query = parse_qs(urlparse(resp.url).query)
        if query.get("select") != [SELECT] or query.get("filter") != [filter_]:
            continue
        if "sample" not in query:
            continue
        stamp = resp.fetched_at.isoformat()
        for work in resp.data.get("results") or []:
            wid = short_id(work.get("id"))
            if wid and work.get("title") and (wid not in found or found[wid][0] < stamp):
                found[wid] = (stamp, work)
    return [
        {
            "openalex_id": wid,
            "title": w["title"],
            "publication_year": w.get("publication_year"),
            "type": w.get("type"),
        }
        for wid, (_stamp, w) in sorted(found.items())
    ]


def write_background_titles(
    con: duckdb.DuckDBPyConnection, paths: Paths, rows: Sequence[dict[str, Any]]
) -> None:
    table = pa.Table.from_pylist(list(rows), schema=BACKGROUND_SCHEMA)
    replace_table(
        con, BACKGROUND_TABLE, table, paths.warehouse / "staging" / f"{BACKGROUND_TABLE}.parquet"
    )
