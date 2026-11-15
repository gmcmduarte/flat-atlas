import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from flatatlas import db
from flatatlas.settings import Settings


def test_connect_creates_ops_tables(settings: Settings):
    con = db.connect(settings.paths)
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert {"ops_harvest_state", "ops_run_log", "ops_quality_report"} <= tables
    assert settings.paths.warehouse_db.exists()


def test_atomic_write_replaces_table(tmp_path: Path):
    target = tmp_path / "works.parquet"
    db.write_parquet_atomic(pa.table({"id": [1, 2]}), target)
    db.write_parquet_atomic(pa.table({"id": [3]}), target)
    assert pq.read_table(target).to_pydict() == {"id": [3]}
    assert list(tmp_path.iterdir()) == [target]  # no temp files left behind


def test_failed_write_leaves_old_table_intact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "works.parquet"
    db.write_parquet_atomic(pa.table({"id": [1, 2]}), target)

    def crash_midway(table, where, *args, **kwargs):
        Path(where).write_bytes(b"PAR1 half a file")
        raise OSError("disk full")

    monkeypatch.setattr(db.pq, "write_table", crash_midway)
    with pytest.raises(OSError, match="disk full"):
        db.write_parquet_atomic(pa.table({"id": [9]}), target)

    monkeypatch.undo()
    assert pq.read_table(target).to_pydict() == {"id": [1, 2]}
    assert list(tmp_path.iterdir()) == [target]


def test_query_write_is_atomic_too(settings: Settings, tmp_path: Path):
    con = db.connect(settings.paths)
    tmp_path = tmp_path / "out"
    target = tmp_path / "q.parquet"
    db.write_query_parquet_atomic(con, "SELECT 1 AS x", target)
    with pytest.raises(Exception):  # noqa: B017 - any DuckDB error
        db.write_query_parquet_atomic(con, "SELECT * FROM no_such_table", target)
    assert pq.read_table(target).to_pydict() == {"x": [1]}
    assert list(tmp_path.iterdir()) == [target]


def test_run_log_records_success_and_failure(settings: Settings):
    con = db.connect(settings.paths)
    with db.run_log(con, "harvest") as run:
        run.count("works", 3)
        run.count("works")
    with pytest.raises(RuntimeError), db.run_log(con, "parse"):
        raise RuntimeError("boom")

    rows = {
        r[0]: r
        for r in con.execute("SELECT stage, status, counts, finished FROM ops_run_log").fetchall()
    }
    assert rows["harvest"][1] == "ok"
    assert json.loads(rows["harvest"][2]) == {"works": 4}
    assert rows["harvest"][3] is not None
    assert rows["parse"][1] == "failed"
