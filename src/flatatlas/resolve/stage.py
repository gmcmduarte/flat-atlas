"""The ``flatatlas resolve`` stage: read staging, resolve, write ``core_*`` (P1-04).

Idempotent: IDs come from the registry (hash of the anchor, never reused), rows are sorted by ID
and carry no timestamps, so a second run on unchanged inputs writes identical tables.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from flatatlas.db import replace_table
from flatatlas.ids import REGISTRY_FILE, IdRegistry
from flatatlas.resolve.config import ResolveConfig, load_resolve_config
from flatatlas.resolve.inputs import Inputs, load_inputs
from flatatlas.resolve.locals import build_work_locals
from flatatlas.resolve.tables import CORE_TABLES, LOCAL_TABLES, to_arrow
from flatatlas.resolve.works import Resolved, resolve_corpus
from flatatlas.settings import Paths
from flatatlas.venues import VenueFacts, VenueRegistry, load_venue_facts, load_venues

log = logging.getLogger(__name__)

CORE_DIR = "core"
LOCAL_DIR = "local"


@dataclass
class StageResult:
    resolved: Resolved
    inputs: Inputs
    written: list[Path]


def table_rows(resolved: Resolved) -> dict[str, list[dict]]:
    return {
        "core_venue": resolved.venues,
        "core_edition": resolved.editions,
        "core_work": resolved.works,
        "core_version": resolved.versions,
        "core_version_match": resolved.matches,
        "core_version_pair": resolved.pair_rows,
        "core_author": resolved.authors,
        "core_authorship": resolved.authorships,
        "core_institution": resolved.institutions,
        "core_citation": resolved.citations,
    }


def write_tables(
    con: duckdb.DuckDBPyConnection,
    paths: Paths,
    resolved: Resolved,
    inputs: Inputs,
    registry: IdRegistry,
) -> list[Path]:
    """Replace every core and work-keyed local table and the registry table (and Parquet copies)."""
    written: list[Path] = []
    rows = table_rows(resolved)
    abstracts, embeddings = build_work_locals(inputs, resolved)
    rows["local_work_abstract"] = abstracts
    rows["local_work_embedding"] = embeddings
    for name in (*CORE_TABLES, *LOCAL_TABLES):
        folder = CORE_DIR if name.startswith("core_") else LOCAL_DIR
        written.append(
            replace_table(
                con, name, to_arrow(name, rows[name]), paths.warehouse / folder / f"{name}.parquet"
            )
        )
    registry_file = registry.save(paths)
    written.append(registry_file)
    table = pq.read_table(registry_file)
    con.register("_registry_rows", table)
    try:
        con.execute("CREATE OR REPLACE TABLE core_id_registry AS SELECT * FROM _registry_rows")
    finally:
        con.unregister("_registry_rows")
    return written


def run(
    con: duckdb.DuckDBPyConnection,
    paths: Paths,
    *,
    config: ResolveConfig | None = None,
    venue_registry: VenueRegistry | None = None,
    facts: VenueFacts | None = None,
) -> StageResult:
    cfg = config or load_resolve_config()
    venues = venue_registry or load_venues()
    venue_facts = facts if facts is not None else load_venue_facts(registry=venues)
    inputs = load_inputs(con)
    registry = IdRegistry.load(paths)
    before = len(registry)
    resolved = resolve_corpus(inputs, cfg, venues, registry, venue_facts)
    resolved.stats["ids_minted"] = len(registry) - before
    written = write_tables(con, paths, resolved, inputs, registry)
    return StageResult(resolved, inputs, written)


__all__ = ["REGISTRY_FILE", "StageResult", "run", "table_rows", "write_tables"]
