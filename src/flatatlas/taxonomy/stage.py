"""Warehouse input and output of the taxonomy stages: mine, cluster, propose."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pyarrow as pa

from flatatlas.db import write_parquet_atomic
from flatatlas.settings import Paths
from flatatlas.text import store as text_store
from flatatlas.text.composite import CompositeParts

PHRASES_FILE = "phrases.parquet"
CLUSTERS_FILE = "clusters.parquet"

_S = pa.string()
PHRASE_SCHEMA = pa.schema(
    [
        ("rank", pa.int32()),
        ("phrase", _S),
        ("key", _S),
        ("n_tokens", pa.int16()),
        ("source", _S),
        ("score", pa.float32()),
        ("ctfidf", pa.float32()),
        ("specificity", pa.float32()),
        ("df", pa.int32()),
        ("df_title", pa.int32()),
        ("df_own", pa.int32()),
        ("df_background", pa.int32()),
        ("weighted_df", pa.float32()),
        ("first_year", pa.int16()),
        ("examples", pa.list_(_S)),
        ("variants", pa.list_(_S)),
        ("merged_from", pa.list_(_S)),
        ("merge_suggestions", pa.list_(pa.struct([("phrase", _S), ("cosine", pa.float32())]))),
        ("openalex_keyword_works", pa.int32()),
    ]
)


class MissingInput(RuntimeError):
    """A table the stage needs is not in the warehouse; the message says which command makes it."""


def require(con: duckdb.DuckDBPyConnection, table: str, hint: str) -> None:
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if table not in have:
        raise MissingInput(f"missing table {table}; {hint}")


def composite_parts(con: duckdb.DuckDBPyConnection) -> list[CompositeParts]:
    require(con, "local_work_text", "run `flatatlas taxonomy composite` first")
    return text_store.read_parts(con)


def work_vectors(con: duckdb.DuckDBPyConnection) -> tuple[list[str], np.ndarray]:
    """Work IDs (sorted) and their SPECTER2 vectors, one per work."""
    require(con, "local_work_embedding", "run `flatatlas resolve` first")
    rows = con.execute(
        "SELECT work_id, vector FROM local_work_embedding ORDER BY work_id"
    ).fetchall()
    ids = [r[0] for r in rows]
    matrix = np.asarray([r[1] for r in rows], dtype=np.float32)
    return ids, matrix


def background_titles(con: duckdb.DuckDBPyConnection) -> list[str]:
    require(con, "stg_background_title", "run `flatatlas harvest background-titles` and parse it")
    rows = con.execute("SELECT title FROM stg_background_title ORDER BY openalex_id").fetchall()
    return [r[0] for r in rows]


def openalex_keywords(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """OpenAlex keywords with the number of pilot works that have them."""
    rows = con.execute(
        "SELECT name, count(DISTINCT openalex_id) FROM stg_openalex_topic "
        "WHERE kind = 'keyword' AND name IS NOT NULL GROUP BY 1 ORDER BY 1"
    ).fetchall()
    return {name: n for name, n in rows}


def write_phrases(paths: Paths, rows: list[dict[str, Any]]) -> Path:
    table = pa.Table.from_pylist(rows, schema=PHRASE_SCHEMA)
    return write_parquet_atomic(table, paths.reports / PHRASES_FILE)


def read_phrases(paths: Paths) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    path = paths.reports / PHRASES_FILE
    if not path.exists():
        raise MissingInput(f"{path} not found; run `flatatlas taxonomy mine` first")
    return pq.read_table(path).to_pylist()


CLUSTER_SCHEMA = pa.schema(
    [
        ("cluster_id", _S),
        ("granularity", pa.int16()),
        ("size", pa.int32()),
        ("label", _S),
        ("terms", pa.list_(_S)),
        ("parent_cluster", _S),
        ("parent_share", pa.float32()),
        ("openalex_topics", pa.list_(pa.struct([("name", _S), ("share", pa.float32())]))),
        (
            "seed_matches",
            pa.list_(
                pa.struct([("scheme", _S), ("id", _S), ("label", _S), ("jaccard", pa.float32())])
            ),
        ),
        ("examples", pa.list_(_S)),
    ]
)
MEMBER_SCHEMA = pa.schema([("cluster_id", _S), ("granularity", pa.int16()), ("work_id", _S)])
MEMBERS_FILE = "cluster_members.parquet"


def openalex_primary_topics(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """``work_id -> name of the primary OpenAlex topic`` (the first version that has one)."""
    rows = con.execute(
        """
        SELECT v.work_id, t.name
        FROM core_version v
        JOIN stg_openalex_topic t ON t.openalex_id = v.openalex_id
        WHERE t.kind = 'topic' AND t.rank = 1
        ORDER BY v.work_id, v.version_id
        """
    ).fetchall()
    out: dict[str, str] = {}
    for wid, name in rows:
        out.setdefault(wid, name)
    return out


def overlap_seeds(seeds_dir: Path) -> list[dict[str, str]]:
    """MSC and CCS seed entries as ``{scheme, id, label}`` (CCS only when ccs.yaml exists)."""
    import yaml

    out = []
    msc = seeds_dir / "msc.yaml"
    if msc.exists():
        for code in yaml.safe_load(msc.read_text(encoding="utf-8"))["codes"]:
            out.append({"scheme": "msc", "id": code["code"], "label": code["ours"]})
    ccs = seeds_dir / "ccs.yaml"
    if ccs.exists():
        for node in yaml.safe_load(ccs.read_text(encoding="utf-8"))["concepts"]:
            out.append({"scheme": "ccs", "id": node["id"], "label": node["label"]})
    return out


def write_clusters(
    paths: Paths, rows: list[dict[str, Any]], members: list[dict[str, Any]]
) -> tuple[Path, Path]:
    a = write_parquet_atomic(
        pa.Table.from_pylist(rows, schema=CLUSTER_SCHEMA), paths.reports / CLUSTERS_FILE
    )
    b = write_parquet_atomic(
        pa.Table.from_pylist(members, schema=MEMBER_SCHEMA), paths.reports / MEMBERS_FILE
    )
    return a, b


def read_table(paths: Paths, name: str, hint: str) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    path = paths.reports / name
    if not path.exists():
        raise MissingInput(f"{path} not found; {hint}")
    return pq.read_table(path).to_pylist()


def citation_pairs(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    rows = con.execute(
        "SELECT citing_work_id, cited_work_id FROM core_citation ORDER BY 1, 2"
    ).fetchall()
    return [(a, b) for a, b in rows]


def cited_by_in_corpus(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    rows = con.execute("SELECT work_id, cited_by_in_corpus FROM core_work").fetchall()
    return {w: int(n or 0) for w, n in rows}


def openalex_primary_topic_ids(con: duckdb.DuckDBPyConnection) -> dict[str, tuple[str, str]]:
    """``work_id -> (topic id, topic name)`` of the primary OpenAlex topic."""
    rows = con.execute(
        """
        SELECT v.work_id, t.topic_id, t.name
        FROM core_version v
        JOIN stg_openalex_topic t ON t.openalex_id = v.openalex_id
        WHERE t.kind = 'topic' AND t.rank = 1
        ORDER BY v.work_id, v.version_id
        """
    ).fetchall()
    out: dict[str, tuple[str, str]] = {}
    for wid, tid, name in rows:
        out.setdefault(wid, (tid, name))
    return out


def seeds_with_structure(seeds_dir: Path) -> list[dict[str, Any]]:
    """Like ``overlap_seeds`` but CCS entries carry their parents (for seed-structure evidence)."""
    import yaml

    out = overlap_seeds(seeds_dir)
    ccs = seeds_dir / "ccs.yaml"
    if ccs.exists():
        parents = {
            n["id"]: n.get("parents") or []
            for n in yaml.safe_load(ccs.read_text(encoding="utf-8"))["concepts"]
        }
        for seed in out:
            if seed["scheme"] == "ccs":
                seed["parents"] = parents.get(seed["id"], [])
    return out
