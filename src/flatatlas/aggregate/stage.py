"""The aggregate stage: warehouse in, edges, aggregates and layout out (P1-09).

Reads the shipped method's tags (``tag_work_topic`` rows with ``provenance.method`` equal to
``method`` in ``config/tagger.yaml``; the other method's rows are ignored, D-100), the works,
authorships and citations, and ``taxonomy/topics.yaml``. Writes ``core_topic``,
``core_topic_edge`` (``subtopic-of`` plus the three lateral types), ``agg_topic_year``,
``agg_topic_author``, ``agg_topic_venue``, ``agg_topic_work`` and ``agg_map_layout``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import duckdb
import numpy as np
import pyarrow as pa

from flatatlas.aggregate import edges as edge_mod
from flatatlas.aggregate import layout as layout_mod
from flatatlas.aggregate import membership as mem
from flatatlas.aggregate import topics as topic_agg
from flatatlas.aggregate.config import AggregateConfig
from flatatlas.db import replace_table
from flatatlas.settings import Paths
from flatatlas.tagging.config import TaggerConfig
from flatatlas.taxonomy import load as tload
from flatatlas.taxonomy.check import TOPICS_FILE, load_topics
from flatatlas.taxonomy.stage import MissingInput, require

LAYOUT_TABLE = "agg_map_layout"
AGG_TABLES = ("agg_topic_year", "agg_topic_author", "agg_topic_venue", "agg_topic_work")


@dataclass
class Inputs:
    graph: mem.TopicGraph
    work_table: topic_agg.WorkTable
    base: np.ndarray
    m: np.ndarray
    citations: tuple[np.ndarray, np.ndarray]
    taxonomy_version: int
    tagger_version: str


@dataclass
class Result:
    counts: dict[str, int]
    edges: dict[str, list[edge_mod.Edge]]
    graph: mem.TopicGraph
    volume: np.ndarray


def _sql_in(values: list[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


def read_inputs(
    con: duckdb.DuckDBPyConnection,
    tagger_cfg: TaggerConfig,
    limit: int | None = None,
) -> Inputs:
    for table, hint in (
        ("core_work", "flatatlas resolve"),
        ("core_version", "flatatlas resolve"),
        ("core_authorship", "flatatlas resolve"),
        ("core_citation", "flatatlas resolve"),
        ("core_venue", "flatatlas resolve"),
        ("tag_work_topic", "flatatlas tag"),
    ):
        require(con, table, hint)
    versions = [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT provenance.tagger_version FROM tag_work_topic "
            "WHERE provenance.method = ?",
            [tagger_cfg.method],
        ).fetchall()
    ]
    if versions != [tagger_cfg.tagger_version]:
        raise MissingInput(
            f"tag_work_topic holds {versions or 'no'} rows of method '{tagger_cfg.method}', "
            f"but the settings say {tagger_cfg.tagger_version}; run `flatatlas tag`"
        )
    file = load_topics(TOPICS_FILE)
    topic_list = [t for t in file.topics if t.status != "deprecated"]
    graph = mem.TopicGraph.from_parents({t.id: t.parents for t in topic_list})

    lim = f"LIMIT {int(limit)}" if limit else ""
    works = con.execute(
        "SELECT w.work_id, w.year, COALESCE(w.cited_by_count, 0), v.venue_id "
        "FROM core_work w LEFT JOIN core_version v ON v.version_id = w.primary_version_id "
        f"ORDER BY w.work_id {lim}"
    ).fetchall()
    work_ids = [r[0] for r in works]
    work_index = {w: i for i, w in enumerate(work_ids)}
    venue_ids = [r[0] for r in con.execute("SELECT venue_id FROM core_venue ORDER BY 1").fetchall()]
    venue_index = {v: i for i, v in enumerate(venue_ids)}

    tags = con.execute(
        "SELECT work_id, topic_id, confidence, derived, provenance.flags "
        "FROM tag_work_topic WHERE provenance.method = ?",
        [tagger_cfg.method],
    ).fetchall()
    tags = [t for t in tags if t[0] in work_index]
    flags: dict[str, set[str]] = {}
    for work_id, _t, _c, _d, fl in tags:
        flags.setdefault(work_id, set()).update(fl or [])
    classes = mem.work_classes(work_ids, flags, {t[0] for t in tags})
    base = mem.base_matrix(work_index, graph.index, ((t[0], t[1], t[2], t[3]) for t in tags))
    m = mem.roll_up(base, graph)

    pairs = con.execute(
        "SELECT DISTINCT v.work_id, a.author_id FROM core_authorship a "
        "JOIN core_version v ON v.version_id = a.version_id ORDER BY 1, 2"
    ).fetchall()
    author_ids = sorted({p[1] for p in pairs})
    author_index = {a: i for i, a in enumerate(author_ids)}
    pairs = [p for p in pairs if p[0] in work_index]
    authorship = (
        np.array([work_index[p[0]] for p in pairs], dtype=np.int64),
        np.array([author_index[p[1]] for p in pairs], dtype=np.int64),
    )
    cites = [
        c
        for c in con.execute("SELECT citing_work_id, cited_work_id FROM core_citation").fetchall()
        if c[0] in work_index and c[1] in work_index
    ]
    citations = (
        np.array([work_index[c[0]] for c in cites], dtype=np.int64),
        np.array([work_index[c[1]] for c in cites], dtype=np.int64),
    )
    table = topic_agg.WorkTable(
        work_ids=work_ids,
        years=np.array([r[1] or 0 for r in works], dtype=np.int64),
        cited_by=np.array([r[2] for r in works], dtype=np.int64),
        venue_idx=np.array([venue_index.get(r[3], -1) for r in works], dtype=np.int64),
        venue_ids=venue_ids,
        classes=classes,
        authorship=authorship,
        author_ids=author_ids,
    )
    return Inputs(
        graph, table, base, m, citations, file.taxonomy_version, tagger_cfg.tagger_version
    )


def edge_table(
    graph: mem.TopicGraph,
    edges: dict[str, list[edge_mod.Edge]],
    taxonomy_version: int,
    aggregate_version: str,
    subtopic_rows: list[dict],
) -> pa.Table:
    rows = list(subtopic_rows)
    for typed in edges.values():
        for e in typed:
            rows.append(
                {
                    "src_topic": graph.ids[e.src],
                    "dst_topic": graph.ids[e.dst],
                    "edge_type": e.edge_type,
                    "weight": e.weight,
                    "confidence": e.confidence,
                    "provenance": {
                        "method": f"{e.method}@{aggregate_version}",
                        "taxonomy_version": taxonomy_version,
                    },
                    "evidence": json.dumps(e.evidence, sort_keys=True),
                    "year_from": None,
                    "year_to": None,
                }
            )
    return pa.Table.from_pylist(rows, schema=tload.SCHEMAS["core_topic_edge"])


def compute(inputs: Inputs, cfg: AggregateConfig) -> dict[str, object]:
    """Everything the stage writes, as in-memory objects (no warehouse access)."""
    graph, works, m = inputs.graph, inputs.work_table, inputs.m
    tagged = works.mask(mem.TAGGED)
    exclude = graph.related_mask()
    edges = edge_mod.compute_edges(
        m,
        tagged,
        works.years,
        inputs.citations,
        works.authorship,
        len(works.author_ids),
        exclude,
        cfg,
    )
    summ = topic_agg.summary(m, works, cfg.present_min)
    volume = summ["volume"]
    primary = layout_mod.primary_parents(graph, inputs.base, m, volume)
    lateral = [(e.src, e.dst, e.weight * e.confidence) for typed in edges.values() for e in typed]
    nodes = layout_mod.compute_layout(graph, volume, primary, lateral, cfg.layout)
    return {
        "edges": edges,
        "summary": summ,
        "layout": layout_mod.layout_table(graph, nodes, volume, cfg.layout.decimals),
        "agg_topic_year": topic_agg.topic_year(m, works, graph.ids, cfg.present_min),
        "agg_topic_author": topic_agg.topic_author(m, works, graph.ids, cfg.present_min),
        "agg_topic_venue": topic_agg.topic_venue(m, works, graph.ids, cfg.present_min),
        "agg_topic_work": topic_agg.topic_work(m, works, graph.ids),
    }


def run(
    con: duckdb.DuckDBPyConnection,
    paths: Paths,
    cfg: AggregateConfig,
    tagger_cfg: TaggerConfig,
    limit: int | None = None,
) -> Result:
    inputs = read_inputs(con, tagger_cfg, limit)
    out = compute(inputs, cfg)
    file = load_topics(TOPICS_FILE)
    topic_rows, subtopic_rows = tload.topic_rows(file)
    replace_table(
        con,
        "core_topic",
        pa.Table.from_pylist(topic_rows, schema=tload.SCHEMAS["core_topic"]),
        paths.warehouse / "core" / "core_topic.parquet",
    )
    replace_table(
        con,
        "core_topic_edge",
        edge_table(
            inputs.graph,
            out["edges"],  # type: ignore[arg-type]
            inputs.taxonomy_version,
            cfg.aggregate_version,
            subtopic_rows,
        ),
        paths.warehouse / "core" / "core_topic_edge.parquet",
    )
    for name in AGG_TABLES:
        replace_table(con, name, out[name], paths.warehouse / "agg" / f"{name}.parquet")  # type: ignore[arg-type]
    replace_table(
        con,
        LAYOUT_TABLE,
        out["layout"],
        paths.warehouse / "agg" / f"{LAYOUT_TABLE}.parquet",  # type: ignore[arg-type]
    )
    classes = inputs.work_table.classes
    edges = out["edges"]
    counts = {
        "works": len(classes),
        "tagged": classes.count(mem.TAGGED),
        "low_confidence": classes.count(mem.LOW_CONFIDENCE),
        "untagged": classes.count(mem.UNTAGGED),
        "topics": inputs.graph.n,
        **{f"edges_{k}": len(v) for k, v in edges.items()},  # type: ignore[union-attr]
        **{name: out[name].num_rows for name in AGG_TABLES},  # type: ignore[union-attr]
    }
    return Result(counts, edges, inputs.graph, out["summary"]["volume"])  # type: ignore[index,arg-type]
