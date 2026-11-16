"""Load ``topics.yaml`` and ``gold.yaml`` into ``core_topic``, ``core_topic_edge``, ``eval_gold``.

The warehouse tables are rebuilt from the files every time (the files are the source of truth,
PLAN §4.3). Only ``subtopic-of`` edges come from the file; the other edge types are computed by
the aggregate stage.
"""

from __future__ import annotations

import json
from typing import Any

import duckdb
import pyarrow as pa

from flatatlas.db import replace_table
from flatatlas.settings import Paths
from flatatlas.taxonomy.schema import GoldFile, TopicsFile, phrase_text, topic_levels

_S = pa.string()
_LIST_S = pa.list_(_S)

SCHEMAS: dict[str, pa.Schema] = {
    "core_topic": pa.schema(
        [
            ("topic_id", _S),
            ("name", _S),
            ("aliases", _LIST_S),
            ("description", _S),
            ("level", pa.int16()),
            ("status", _S),
            ("xref_ccs", _LIST_S),
            ("xref_msc", _LIST_S),
            ("xref_openalex", _LIST_S),
            ("seed_work_ids", _LIST_S),
            ("include_phrases", _LIST_S),
            ("exclude_phrases", _LIST_S),
            ("origin", _S),
            ("reviewed", pa.bool_()),
            ("taxonomy_version", pa.int32()),
        ]
    ),
    "core_topic_edge": pa.schema(
        [
            ("src_topic", _S),
            ("dst_topic", _S),
            ("edge_type", _S),
            ("weight", pa.float32()),
            ("confidence", pa.float32()),
            ("provenance", pa.struct([("method", _S), ("taxonomy_version", pa.int32())])),
            ("evidence", _S),  # JSON text of the counts behind the edge
            ("year_from", pa.int16()),
            ("year_to", pa.int16()),
        ]
    ),
    "eval_gold": pa.schema(
        [
            ("work_id", _S),
            ("topic_id", _S),
            ("split", _S),
            ("sampling", _S),
            ("blind", pa.bool_()),
            ("taxonomy_version", pa.int32()),
        ]
    ),
}

EDGE_METHOD = "topics.yaml"


def topic_rows(file: TopicsFile) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``core_topic`` and ``core_topic_edge`` rows, in file order."""
    levels = topic_levels(file.topics)
    topics, edges = [], []
    for t in file.topics:
        topics.append(
            {
                "topic_id": t.id,
                "name": t.name,
                "aliases": list(t.aliases),
                "description": t.description,
                "level": levels.get(t.id),
                "status": t.status,
                "xref_ccs": list(t.xref.ccs),
                "xref_msc": list(t.xref.msc),
                "xref_openalex": list(t.xref.openalex),
                "seed_work_ids": list(t.seed_works),
                "include_phrases": [phrase_text(p) for p in t.include_phrases],
                "exclude_phrases": [phrase_text(p) for p in t.exclude_phrases],
                "origin": t.origin,
                "reviewed": t.reviewed,
                "taxonomy_version": file.taxonomy_version,
            }
        )
        for parent in t.parents:
            edges.append(
                {
                    "src_topic": t.id,
                    "dst_topic": parent,
                    "edge_type": "subtopic-of",
                    "weight": 1.0,
                    # A reviewed topic's parents were read by a person; others are proposals.
                    "confidence": 1.0 if t.reviewed else None,
                    "provenance": {
                        "method": EDGE_METHOD,
                        "taxonomy_version": file.taxonomy_version,
                    },
                    "evidence": json.dumps(t.evidence or {}, sort_keys=True),
                    "year_from": None,
                    "year_to": None,
                }
            )
    return topics, edges


def gold_rows(gold: GoldFile) -> list[dict[str, Any]]:
    return [
        {
            "work_id": w.work,
            "topic_id": label,
            "split": w.split,
            "sampling": w.sampling,
            "blind": w.blind,
            "taxonomy_version": gold.taxonomy_version,
        }
        for w in gold.works
        for label in w.labels
    ]


def write_topics(con: duckdb.DuckDBPyConnection, paths: Paths, file: TopicsFile) -> dict[str, int]:
    topics, edges = topic_rows(file)
    for name, rows in (("core_topic", topics), ("core_topic_edge", edges)):
        table = pa.Table.from_pylist(rows, schema=SCHEMAS[name])
        replace_table(con, name, table, paths.warehouse / "core" / f"{name}.parquet")
    return {"topics": len(topics), "edges": len(edges)}


def write_gold(con: duckdb.DuckDBPyConnection, paths: Paths, gold: GoldFile) -> dict[str, int]:
    rows = gold_rows(gold)
    table = pa.Table.from_pylist(rows, schema=SCHEMAS["eval_gold"])
    replace_table(con, "eval_gold", table, paths.warehouse / "eval" / "eval_gold.parquet")
    return {"works": len(gold.works), "labels": len(rows)}


def known_work_resolver(con: duckdb.DuckDBPyConnection | None, paths: Paths):
    """A ``resolve_work`` function for ``check_gold``: the warehouse's works and the ID registry.

    Returns None for every ID when there is no warehouse yet, so a gold file cannot pass the check
    on a machine that has no works (the rule is vacuous only while the file does not exist).
    """
    from flatatlas.ids import IdRegistry, RegistryError

    works: set[str] = set()
    if con is not None:
        have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "core_work" in have:
            works = {r[0] for r in con.execute("SELECT work_id FROM core_work").fetchall()}
    registry_path = paths.warehouse / "core_id_registry.parquet"
    registry = IdRegistry.load(paths) if registry_path.exists() else None

    def resolve(work_id: str) -> str | None:
        if work_id in works:
            return work_id
        if registry is not None and work_id in registry:
            try:
                return registry.resolve(work_id)
            except RegistryError:
                return None
        return None

    return resolve
