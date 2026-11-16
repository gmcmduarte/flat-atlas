"""Everything the resolve stage reads, as plain rows (so the rules can be tested without DuckDB)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import duckdb

Row = dict[str, Any]


@dataclass
class Inputs:
    """Staging and local tables of one profile, as lists of dicts."""

    editions: list[Row] = field(default_factory=list)  # stg_dblp_edition
    papers: list[Row] = field(default_factory=list)  # stg_dblp_paper
    authorships: list[Row] = field(default_factory=list)  # stg_dblp_authorship
    authors: list[Row] = field(default_factory=list)  # stg_dblp_author
    oa_lookup: list[Row] = field(default_factory=list)  # stg_openalex_lookup
    oa_works: list[Row] = field(default_factory=list)  # stg_openalex_work
    oa_authorships: list[Row] = field(default_factory=list)  # stg_openalex_authorship
    oa_references: list[Row] = field(default_factory=list)  # stg_openalex_reference
    s2_lookup: list[Row] = field(default_factory=list)  # stg_s2_lookup
    s2_papers: list[Row] = field(default_factory=list)  # stg_s2_paper
    s2_references: list[Row] = field(default_factory=list)  # stg_s2_reference
    crossref: list[Row] = field(default_factory=list)  # stg_crossref_work
    # local_embedding: dblp_key -> row (model, source, s2_corpus_id, input_kind, abstract_source,
    # vector); local_abstract: dblp_key -> (source, text) as chosen by ``best_abstracts``.
    embeddings: dict[str, Row] = field(default_factory=dict)
    abstracts: dict[str, tuple[str, str]] = field(default_factory=dict)


REQUIRED_TABLES: Mapping[str, str] = {
    "editions": "stg_dblp_edition",
    "papers": "stg_dblp_paper",
    "authorships": "stg_dblp_authorship",
    "authors": "stg_dblp_author",
    "oa_lookup": "stg_openalex_lookup",
    "oa_works": "stg_openalex_work",
    "oa_authorships": "stg_openalex_authorship",
    "oa_references": "stg_openalex_reference",
    "s2_lookup": "stg_s2_lookup",
    "s2_papers": "stg_s2_paper",
    "s2_references": "stg_s2_reference",
    "crossref": "stg_crossref_work",
}

ORDER_BY: Mapping[str, str] = {
    "stg_dblp_edition": "edition_key",
    "stg_dblp_paper": "dblp_key",
    "stg_dblp_authorship": "dblp_key, position",
    "stg_dblp_author": "pid",
    "stg_openalex_lookup": "dblp_key",
    "stg_openalex_work": "openalex_id",
    "stg_openalex_authorship": "openalex_id, position, institution_id NULLS LAST",
    "stg_openalex_reference": "citing_openalex_id, position",
    "stg_s2_lookup": "dblp_key",
    "stg_s2_paper": "s2_corpus_id",
    "stg_s2_reference": "citing_corpus_id, cited_corpus_id",
    "stg_crossref_work": "doi",
}


class MissingInputs(LookupError):
    """A staging table the stage needs does not exist yet."""


def table_names(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {r[0] for r in con.execute("SHOW TABLES").fetchall()}


def _rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[Row]:
    cursor = con.execute(sql)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def load_inputs(
    con: duckdb.DuckDBPyConnection, *, venue_ids: Sequence[str] | None = None
) -> Inputs:
    """Read the staging tables. ``venue_ids`` limits the papers (and their editions) to a profile.

    Raises ``MissingInputs`` naming the commands to run when a table is absent.
    """
    have = table_names(con)
    missing = sorted(t for t in REQUIRED_TABLES.values() if t not in have)
    if missing:
        raise MissingInputs(
            "missing tables: "
            + ", ".join(missing)
            + " (run `flatatlas parse dblp`, `parse openalex`, `parse crossref`, `parse s2` first)"
        )
    data: dict[str, list[Row]] = {}
    for attr, table in REQUIRED_TABLES.items():
        data[attr] = _rows(con, f"SELECT * FROM {table} ORDER BY {ORDER_BY[table]}")
    inputs = Inputs(**data)
    if venue_ids is not None:
        wanted = set(venue_ids)
        inputs.editions = [e for e in inputs.editions if e["venue_id"] in wanted]
        inputs.papers = [p for p in inputs.papers if p["venue_id"] in wanted]
        keys = {p["dblp_key"] for p in inputs.papers}
        inputs.authorships = [a for a in inputs.authorships if a["dblp_key"] in keys]
        used = {a["pid"] for a in inputs.authorships}
        inputs.authors = [a for a in inputs.authors if a["pid"] in used]

    if "local_embedding" in have:
        for row in _rows(con, "SELECT * FROM local_embedding ORDER BY dblp_key"):
            inputs.embeddings[row["dblp_key"]] = row
    if "local_abstract" in have:
        from flatatlas.abstracts import best_abstracts

        inputs.abstracts = best_abstracts(con)
    return inputs
