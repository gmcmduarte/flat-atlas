"""The ``local_embedding`` table (PLAN §4.2): one SPECTER2 vector per paper.

Local-only: it lives in the warehouse and in ``warehouse/local/local_embedding.parquet`` and is
never exported. It is keyed by ``dblp_key`` until the resolve stage (P1-04) mints work IDs, the
same way ``local_abstract`` is.

Each paper has **exactly one** row. Sources are ranked (``SOURCE_PRIORITY``): a Semantic Scholar
vector replaces a locally computed one, so re-running ``parse s2`` after a later harvest can only
make the table better, never leave two vectors for one paper.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import duckdb
import numpy as np
import pyarrow as pa

from flatatlas.db import replace_table
from flatatlas.settings import Paths

DIM = 768
TABLE = "local_embedding"
SOURCE_PRIORITY = ("s2", "local")  # best first

_S = pa.string()
LOCAL_EMBEDDING_SCHEMA = pa.schema(
    [
        ("dblp_key", _S),
        ("model", _S),  # e.g. "specter_v2" (Semantic Scholar) or the Hugging Face repo + adapter
        ("source", _S),  # s2 | local
        ("s2_corpus_id", pa.int64()),  # s2 rows only
        ("input_kind", _S),  # local rows: "title+abstract" or "title"; s2 rows: null (not stated)
        ("abstract_source", _S),  # local rows: where the abstract came from
        ("vector", pa.list_(pa.float32(), DIM)),
    ]
)
_COLUMNS = [f.name for f in LOCAL_EMBEDDING_SCHEMA]


def table_exists(con: duckdb.DuckDBPyConnection) -> bool:
    return TABLE in {r[0] for r in con.execute("SHOW TABLES").fetchall()}


def read_rows(con: duckdb.DuckDBPyConnection, *, source: str | None = None) -> list[dict[str, Any]]:
    """All rows (optionally of one source) as dicts; ``vector`` is a list of floats."""
    if not table_exists(con):
        return []
    sql = f"SELECT {', '.join(_COLUMNS)} FROM {TABLE}"
    args: list[Any] = []
    if source is not None:
        sql += " WHERE source = ?"
        args.append(source)
    table = con.sql(sql, params=args or None).to_arrow_table()
    return table.to_pylist()


def check_vector(vector: Sequence[float]) -> None:
    if len(vector) != DIM:
        raise ValueError(f"expected a {DIM}-dimensional vector, got {len(vector)}")


def one_per_key(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the best-ranked row of each ``dblp_key``; output is sorted by key."""
    rank = {source: i for i, source in enumerate(SOURCE_PRIORITY)}
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["dblp_key"]
        current = best.get(key)
        if current is None or rank.get(row["source"], 99) < rank.get(current["source"], 99):
            best[key] = row
    return [best[k] for k in sorted(best)]


def write_source(
    con: duckdb.DuckDBPyConnection, paths: Paths, source: str, rows: list[dict[str, Any]]
) -> int:
    """Replace the ``source`` rows, keep the other sources', enforce one row per paper.

    Returns the number of rows in the table afterwards.
    """
    if source not in SOURCE_PRIORITY:
        raise ValueError(f"unknown embedding source {source!r}")
    for row in rows:
        check_vector(row["vector"])
        if row["source"] != source:
            raise ValueError(f"row for {row['dblp_key']} has source {row['source']!r}")
    kept = [r for r in read_rows(con) if r["source"] != source]
    merged = one_per_key(kept + rows)
    normalised = [{c: r.get(c) for c in _COLUMNS} for r in merged]
    table = pa.Table.from_pylist(normalised, schema=LOCAL_EMBEDDING_SCHEMA)
    replace_table(con, TABLE, table, paths.warehouse / "local" / f"{TABLE}.parquet")
    return len(merged)


def coverage(con: duckdb.DuckDBPyConnection, keys: Sequence[str]) -> dict[str, Any]:
    """How many of ``keys`` have a vector, by source, and whether any key has more than one."""
    rows = read_rows(con)
    per_key: dict[str, int] = {}
    by_source: dict[str, int] = {}
    wanted = set(keys)
    for r in rows:
        if r["dblp_key"] in wanted:
            per_key[r["dblp_key"]] = per_key.get(r["dblp_key"], 0) + 1
            by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    return {
        "papers": len(wanted),
        "with_vector": len(per_key),
        "missing": len(wanted) - len(per_key),
        "duplicated": sum(1 for n in per_key.values() if n > 1),
        "by_source": dict(sorted(by_source.items())),
    }


# -- similarity ----------------------------------------------------------------------------------


def as_matrix(vectors: Sequence[Sequence[float]]) -> np.ndarray:
    return np.asarray(vectors, dtype=np.float32).reshape(len(vectors), DIM)


def normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1, norms)


def cosine_pairs(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cosine similarity of row ``i`` of ``a`` with row ``i`` of ``b``."""
    return np.einsum("ij,ij->i", normalise(a), normalise(b))


def cosine_topk(
    matrix: np.ndarray,
    query: Sequence[float] | np.ndarray,
    k: int = 10,
    *,
    exclude: int | None = None,
) -> list[tuple[int, float]]:
    """The ``k`` rows of ``matrix`` closest to ``query`` as ``(row index, cosine)``, best first.

    Plain numpy; at pilot size (thousands of rows) a vector database is not needed. ``exclude``
    drops one row (the query's own).
    """
    if len(matrix) == 0 or k <= 0:
        return []
    q = np.asarray(query, dtype=np.float32).reshape(1, -1)
    scores = (normalise(np.asarray(matrix, dtype=np.float32)) @ normalise(q).T).ravel()
    if exclude is not None and 0 <= exclude < len(scores):
        scores[exclude] = -np.inf
    k = min(k, len(scores) - (1 if exclude is not None else 0))
    if k <= 0:
        return []
    top = np.argpartition(-scores, k - 1)[:k]
    top = top[np.lexsort((top, -scores[top]))]  # best first, ties by row index
    return [(int(i), float(scores[i])) for i in top]
