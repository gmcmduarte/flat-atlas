"""Read the warehouse into ``WorkInputs`` and store the composite text (local-only table).

``local_work_text`` has one row per work, with the parts separate and the joined text. It lives in
``warehouse/local/`` and is never exported (abstracts and TLDRs are in it).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import duckdb
import pyarrow as pa

from flatatlas.db import replace_table
from flatatlas.settings import Paths
from flatatlas.text.composite import CompositeParts, Reference, WorkInputs, build_parts

TABLE = "local_work_text"
_S = pa.string()
SCHEMA = pa.schema(
    [
        ("work_id", _S),
        ("title", _S),
        ("venue", _S),
        ("year", pa.int16()),
        ("reference_titles", pa.list_(_S)),
        ("abstract", _S),
        ("tldr", _S),
        ("abstract_source", _S),
        ("n_references", pa.int32()),
        ("n_references_with_title", pa.int32()),
        ("text", _S),
    ]
)


def load_inputs(
    con: duckdb.DuckDBPyConnection, *, work_ids: list[str] | None = None
) -> list[WorkInputs]:
    """One ``WorkInputs`` per work (all works, or the listed ones), ordered by work ID."""
    where = ""
    args: list[Any] = []
    if work_ids is not None:
        where = f"WHERE w.work_id IN ({', '.join('?' * len(work_ids))})"
        args = list(work_ids)
    works = con.execute(
        f"""
        SELECT w.work_id, w.title, w.year, v.acronym
        FROM core_work w
        LEFT JOIN core_version pv ON pv.version_id = w.primary_version_id
        LEFT JOIN core_venue v ON v.venue_id = pv.venue_id
        {where}
        ORDER BY w.work_id
        """,
        args,
    ).fetchall()

    abstracts = {
        wid: (source, text)
        for wid, source, text in con.execute(
            "SELECT work_id, source, text FROM local_work_abstract WHERE text <> ''"
        ).fetchall()
    }

    # OpenAlex IDs of each work (all versions) and the S2 TLDR of the first version that has one.
    s2_tldr = dict(
        con.execute(
            "SELECT s2_corpus_id, tldr FROM stg_s2_paper WHERE tldr IS NOT NULL AND tldr <> ''"
        ).fetchall()
    )
    oa_ids: dict[str, set[str]] = defaultdict(set)
    tldr: dict[str, str] = {}
    for wid, oid, corpus in con.execute(
        "SELECT work_id, openalex_id, s2_corpus_id FROM core_version ORDER BY version_id"
    ).fetchall():
        if oid:
            oa_ids[wid].add(oid)
        if corpus in s2_tldr and wid not in tldr:
            tldr[wid] = s2_tldr[corpus]

    titles = {
        oid: (title, source == "pilot", kind)
        for oid, title, source, kind in con.execute(
            "SELECT openalex_id, title, source, type FROM stg_reference_title"
        ).fetchall()
    }
    cited_by_pilot = dict(
        con.execute(
            "SELECT cited_openalex_id, count(DISTINCT citing_openalex_id) "
            "FROM stg_openalex_reference GROUP BY 1"
        ).fetchall()
    )
    refs_of: dict[str, list[str]] = defaultdict(list)
    for citing, cited in con.execute(
        "SELECT citing_openalex_id, cited_openalex_id FROM stg_openalex_reference"
    ).fetchall():
        refs_of[citing].append(cited)

    out = []
    for wid, title, year, venue in works:
        refs = []
        for oid in sorted(oa_ids.get(wid, ())):
            for cited in refs_of.get(oid, ()):
                ref_title, in_corpus, kind = titles.get(cited, (None, False, None))
                n_citing = int(cited_by_pilot.get(cited, 0))
                refs.append(Reference(cited, ref_title, in_corpus, n_citing, kind))
        source, text = abstracts.get(wid, (None, None))
        out.append(
            WorkInputs(
                work_id=wid,
                title=title or "",
                venue=venue,
                year=year,
                abstract=text,
                abstract_source=source,
                tldr=tldr.get(wid),
                references=tuple(refs),
            )
        )
    return out


def build_all(
    con: duckdb.DuckDBPyConnection, *, work_ids: list[str] | None = None
) -> list[CompositeParts]:
    return [build_parts(w) for w in load_inputs(con, work_ids=work_ids)]


def to_rows(parts: list[CompositeParts]) -> list[dict[str, Any]]:
    return [
        {
            "work_id": p.work_id,
            "title": p.title,
            "venue": p.venue or None,
            "year": int(p.year) if p.year else None,
            "reference_titles": list(p.reference_titles),
            "abstract": p.abstract or None,
            "tldr": p.tldr or None,
            "abstract_source": p.abstract_source,
            "n_references": p.n_references,
            "n_references_with_title": p.n_references_with_title,
            "text": p.text,
        }
        for p in parts
    ]


def write_table(con: duckdb.DuckDBPyConnection, paths: Paths, parts: list[CompositeParts]) -> int:
    table = pa.Table.from_pylist(to_rows(parts), schema=SCHEMA)
    replace_table(con, TABLE, table, paths.warehouse / "local" / f"{TABLE}.parquet")
    return len(parts)


def read_parts(con: duckdb.DuckDBPyConnection) -> list[CompositeParts]:
    """The stored composite text, as parts (for mining and clustering)."""
    rows = con.execute(
        "SELECT work_id, title, venue, year, reference_titles, abstract, tldr, abstract_source, "
        "n_references, n_references_with_title FROM local_work_text ORDER BY work_id"
    ).fetchall()
    return [
        CompositeParts(
            work_id=r[0],
            title=r[1] or "",
            venue=r[2] or "",
            year=str(r[3]) if r[3] else "",
            reference_titles=tuple(r[4] or ()),
            abstract=r[5] or "",
            tldr=r[6] or "",
            n_references=r[8] or 0,
            n_references_with_title=r[9] or 0,
            abstract_source=r[7],
        )
        for r in rows
    ]
