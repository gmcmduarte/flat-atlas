"""DuckDB warehouse helpers: connection, operational tables, atomic Parquet writes, run log.

The warehouse is one DuckDB file. Only one process can write to it at a time, so a long job
holding it open blocks other writers (and ``flatatlas status``, which says so).
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from flatatlas.settings import Paths

OPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ops_harvest_state (
    source VARCHAR NOT NULL,
    job_key VARCHAR NOT NULL,
    "cursor" VARCHAR,
    status VARCHAR NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    n_items BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (source, job_key)
);
CREATE TABLE IF NOT EXISTS ops_run_log (
    run_id VARCHAR PRIMARY KEY,
    stage VARCHAR NOT NULL,
    started TIMESTAMP NOT NULL,
    finished TIMESTAMP,
    status VARCHAR NOT NULL,
    counts VARCHAR
);
CREATE TABLE IF NOT EXISTS ops_quality_report (
    run_id VARCHAR,
    "check" VARCHAR,
    value DOUBLE,
    threshold DOUBLE,
    passed BOOLEAN
);
"""


def utcnow() -> datetime:
    """Naive UTC timestamp, the form stored in the TIMESTAMP columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def connect(path: Path | Paths, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the warehouse. Writable connections create the file and the ``ops_*`` tables."""
    db_path = path.warehouse_db if isinstance(path, Paths) else Path(path)
    if read_only:
        return duckdb.connect(str(db_path), read_only=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(OPS_SCHEMA)
    return con


# -- atomic Parquet writes --------------------------------------------------------------------


def _tmp_beside(path: Path) -> Path:
    return path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")


def write_parquet_atomic(table: pa.Table, path: Path) -> Path:
    """Write ``table`` to ``path`` via a temp file and a rename; the old file survives a failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_beside(path)
    try:
        pq.write_table(table, tmp)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def replace_table(
    con: duckdb.DuckDBPyConnection, name: str, table: pa.Table, parquet_path: Path
) -> Path:
    """Replace warehouse table ``name`` with ``table`` and write a Parquet copy of it."""
    con.register("_replace_rows", table)
    try:
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _replace_rows")
    finally:
        con.unregister("_replace_rows")
    return write_parquet_atomic(table, parquet_path)


def write_text_atomic(path: Path, text: str) -> Path:
    """Write a text file via a temp file and a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_beside(path)
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def write_query_parquet_atomic(con: duckdb.DuckDBPyConnection, query: str, path: Path) -> Path:
    """Same as ``write_parquet_atomic`` but for the result of a DuckDB query."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_beside(path)
    try:
        con.execute(f"COPY ({query}) TO '{tmp.as_posix()}' (FORMAT PARQUET)")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


# -- run log ----------------------------------------------------------------------------------


@dataclass
class RunRecord:
    run_id: str
    stage: str
    counts: dict[str, int | float | str] = field(default_factory=dict)

    def count(self, name: str, n: int = 1) -> None:
        self.counts[name] = int(self.counts.get(name, 0)) + n


@contextmanager
def run_log(
    con: duckdb.DuckDBPyConnection,
    stage: str,
    *,
    clock: Callable[[], datetime] = utcnow,
) -> Iterator[RunRecord]:
    """Record a pipeline run in ``ops_run_log``: ``ok``, ``failed`` or ``interrupted``."""
    record = RunRecord(run_id=f"{clock():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}", stage=stage)
    con.execute(
        "INSERT INTO ops_run_log (run_id, stage, started, status) VALUES (?, ?, ?, 'running')",
        [record.run_id, stage, clock()],
    )
    status = "ok"
    try:
        yield record
    except KeyboardInterrupt:
        status = "interrupted"
        raise
    except BaseException:
        status = "failed"
        raise
    finally:
        con.execute(
            "UPDATE ops_run_log SET finished = ?, status = ?, counts = ? WHERE run_id = ?",
            [clock(), status, json.dumps(record.counts, sort_keys=True), record.run_id],
        )
