"""Resumable cursor paging (PLAN §5.1).

``paged()`` stores the cursor in ``ops_harvest_state`` after every page, so a killed job restarts
at the page it had not finished. It does not touch the network itself: ``fetch_page`` does, via a
``SourceClient``, whose cache makes re-fetching the interrupted page free.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import duckdb

from flatatlas.db import utcnow
from flatatlas.log import Progress


@dataclass(frozen=True)
class Page:
    """One page of results. ``next_cursor`` is None on the last page."""

    items: list[Any]
    next_cursor: str | None


@dataclass(frozen=True)
class HarvestState:
    source: str
    job_key: str
    cursor: str | None
    status: str  # running | interrupted | done
    n_items: int


def get_state(con: duckdb.DuckDBPyConnection, source: str, job_key: str) -> HarvestState | None:
    row = con.execute(
        'SELECT "cursor", status, n_items FROM ops_harvest_state WHERE source = ? AND job_key = ?',
        [source, job_key],
    ).fetchone()
    return None if row is None else HarvestState(source, job_key, row[0], row[1], row[2])


def _save(
    con: duckdb.DuckDBPyConnection,
    source: str,
    job_key: str,
    cursor: str | None,
    status: str,
    n_items: int,
) -> None:
    con.execute(
        """
        INSERT INTO ops_harvest_state (source, job_key, "cursor", status, updated_at, n_items)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (source, job_key) DO UPDATE SET
            "cursor" = excluded."cursor", status = excluded.status,
            updated_at = excluded.updated_at, n_items = excluded.n_items
        """,
        [source, job_key, cursor, status, utcnow(), n_items],
    )


def paged(
    con: duckdb.DuckDBPyConnection,
    source: str,
    job_key: str,
    fetch_page: Callable[[str | None], Page],
    *,
    restart: bool = False,
    progress: Progress | None = None,
) -> Iterator[Page]:
    """Yield pages from ``fetch_page(cursor)`` until ``next_cursor`` is None.

    ``fetch_page(None)`` fetches the first page. The loop body runs between ``yield`` and the next
    ``fetch_page`` call; the cursor is stored when the loop asks for the next page, so work on a
    page that was interrupted is repeated on resume (at-least-once; keep it idempotent).
    A job already ``done`` yields nothing unless ``restart=True``.
    """
    state = None if restart else get_state(con, source, job_key)
    if state is not None and state.status == "done":
        return
    cursor = state.cursor if state else None
    n_items = state.n_items if state else 0
    _save(con, source, job_key, cursor, "running", n_items)

    while True:
        try:
            page = fetch_page(cursor)
            yield page
        except BaseException:  # includes GeneratorExit and KeyboardInterrupt
            _save(con, source, job_key, cursor, "interrupted", n_items)
            raise
        n_items += len(page.items)
        if progress is not None:
            progress.update(len(page.items))
        if page.next_cursor is None:
            _save(con, source, job_key, None, "done", n_items)
            return
        cursor = page.next_cursor
        _save(con, source, job_key, cursor, "running", n_items)
