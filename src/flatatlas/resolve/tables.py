"""Arrow schemas of the ``core_*`` tables (PLAN §4.2) and the local work-keyed tables."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pyarrow as pa

S = pa.string()
LIST_S = pa.list_(pa.string())

SCHEMAS: dict[str, pa.Schema] = {
    "core_venue": pa.schema(
        [
            ("venue_id", S),
            ("acronym", S),
            ("name", S),
            ("kind", S),
            ("tier", S),
            ("dblp_stream", S),
            ("openalex_source_ids", LIST_S),
            ("issn", LIST_S),
            ("publisher", S),
            ("first_year", pa.int16()),
            ("last_year", pa.int16()),
            ("successor_of", LIST_S),
            ("homepage", S),
        ]
    ),
    "core_edition": pa.schema(
        [
            ("edition_id", S),
            ("venue_id", S),
            ("year", pa.int16()),
            ("label", S),
            ("dblp_toc_key", S),
            ("location", S),
            ("proceedings_doi", S),
            ("submissions", pa.int32()),
            ("accepted", pa.int32()),
            ("acceptance_rate", pa.float32()),
            ("acceptance_source_url", S),
            ("acceptance_source_note", S),
        ]
    ),
    "core_work": pa.schema(
        [
            ("work_id", S),
            ("title", S),
            ("title_norm", S),
            ("year", pa.int16()),
            ("primary_version_id", S),
            ("work_type", S),
            ("is_survey", pa.bool_()),
            ("survey_confidence", pa.float32()),
            ("language", S),
            ("has_abstract", pa.bool_()),
            ("cited_by_count", pa.int32()),
            ("cited_by_in_corpus", pa.int32()),
            ("scope_status", S),
            ("scope_score", pa.float32()),
            ("scope_reason", S),
            (
                "provenance",
                pa.struct([("sources", LIST_S), ("n_versions", pa.int16())]),
            ),
        ]
    ),
    "core_version": pa.schema(
        [
            ("version_id", S),
            ("work_id", S),
            ("edition_id", S),
            ("venue_id", S),
            ("year", pa.int16()),
            ("volume", S),
            ("issue", S),
            ("pages", S),
            ("page_count", pa.int16()),
            ("doi", S),
            ("dblp_key", S),
            ("openalex_id", S),
            ("s2_corpus_id", pa.int64()),
            ("crossref_type", S),
            ("zbmath_id", S),
            ("url_landing", S),
            ("url_oa", S),
            ("merge_confidence", pa.float32()),
            ("merge_method", S),
        ]
    ),
    "core_version_match": pa.schema(
        [
            ("version_id", S),
            ("source", S),
            ("external_id", S),
            ("method", S),
            ("confidence", pa.float32()),
            ("title_similarity", pa.float32()),
            ("year_diff", pa.int16()),
            ("first_author_agrees", pa.bool_()),
        ]
    ),
    "core_version_pair": pa.schema(
        [
            ("earlier_version_id", S),
            ("later_version_id", S),
            ("score", pa.float32()),
            ("verdict", S),
            ("method", S),
            ("title", pa.float32()),
            ("authors", pa.float32()),
            ("embedding", pa.float32()),
            ("extra", pa.float32()),
            ("reasons", S),
        ]
    ),
    "core_author": pa.schema(
        [
            ("author_id", S),
            ("display_name", S),
            ("name_variants", LIST_S),
            ("dblp_pid", S),
            ("orcid", S),
            ("openalex_ids", LIST_S),
            ("s2_ids", LIST_S),
            ("resolution_confidence", pa.float32()),
            ("resolution_method", S),
        ]
    ),
    "core_authorship": pa.schema(
        [
            ("version_id", S),
            ("author_id", S),
            ("position", pa.int16()),
            ("raw_name", S),
            ("affiliation_raw", S),
            ("institution_id", S),
            ("country_code", S),
            ("source", S),
        ]
    ),
    "core_institution": pa.schema([("institution_id", S), ("name", S), ("country_code", S)]),
    "core_citation": pa.schema(
        [
            ("citing_work_id", S),
            ("cited_work_id", S),
            ("sources", LIST_S),
            ("is_influential", pa.bool_()),
        ]
    ),
    # Local only, never exported (CLAUDE.md rule 2).
    "local_work_abstract": pa.schema(
        [("work_id", S), ("dblp_key", S), ("source", S), ("text", S), ("n_chars", pa.int32())]
    ),
    "local_work_embedding": pa.schema(
        [
            ("work_id", S),
            ("dblp_key", S),
            ("model", S),
            ("source", S),
            ("s2_corpus_id", pa.int64()),
            ("input_kind", S),
            ("abstract_source", S),
            ("vector", pa.list_(pa.float32())),
        ]
    ),
}

CORE_TABLES = tuple(name for name in SCHEMAS if name.startswith("core_"))
LOCAL_TABLES = tuple(name for name in SCHEMAS if name.startswith("local_"))


def to_arrow(name: str, rows: Sequence[dict[str, Any]]) -> pa.Table:
    """Rows to an Arrow table with the declared schema (a column the rows lack is an error)."""
    schema = SCHEMAS[name]
    columns = {field.name: [row[field.name] for row in rows] for field in schema}
    return pa.Table.from_pydict(columns, schema=schema)
