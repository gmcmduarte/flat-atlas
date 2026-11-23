"""Release -> static JSON for the site (PLAN §11.2, P1-09).

Reads a verified release folder (never the warehouse, so what the site shows is what was
released) and writes ``topics.json``, ``topic/<id>.json``, ``works/<shard>.json``,
``authors/<shard>.json``, ``venue/<id>.json``, ``map.json``, ``search/index.json`` and
``meta.json``. Every file is built from the models in ``export/models.py``, so it is validated as
it is made. Works and authors are sharded by the first two hex characters of the SHA-256 of their
ID, the same rule as ``shardOf`` in ``StaticDataSource.ts``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
from pydantic import BaseModel

from flatatlas.export import models as m
from flatatlas.release import build as release_build

TOP_PAPERS = 50
KEY_AUTHORS = 20
EDGES_PER_TYPE = 10
AUTHOR_TOPICS = 15
COAUTHORS = 20
VENUE_TOPICS = 10
VENUE_TOP_PAPERS = 30
CARD_AUTHORS = 3  # author names shown on a paper card
RELATED_WORKS = 100  # references or citers listed on a paper page, at most
SIGNAL_DECIMALS = 3
MAX_BYTES = 30 * 1024 * 1024  # PLAN §11.2: pilot data under 30 MB

# Everything this module writes, so a re-run removes stale files and nothing else.
MANAGED = ("topics.json", "topic", "works", "authors", "venue", "map.json", "search", "meta.json")
LATERAL = ("related", "builds-on", "shared-community")


class ExportError(RuntimeError):
    pass


@dataclass
class ExportResult:
    out: Path
    files: int = 0
    bytes: int = 0
    by_part: dict[str, int] = field(default_factory=dict)


def shard_of(identifier: str) -> str:
    """First two hex characters of the SHA-256 of the ID (256 shards)."""
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:2]


def latest_release(releases: Path) -> Path:
    found = [p for p in releases.glob("v*") if p.is_dir() and (p / "manifest.json").exists()]
    if not found:
        raise ExportError(f"no release in {releases}; run `flatatlas release build` first")

    def key(p: Path) -> tuple[int, ...]:
        return tuple(int(x) for x in p.name[1:].split("."))

    return max(found, key=key)


def _open(release: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    for path in sorted(release.glob("*.parquet")):
        con.execute(f"CREATE VIEW {path.stem} AS SELECT * FROM read_parquet('{path.as_posix()}')")
    return con


def _dump(model: BaseModel) -> dict[str, Any]:
    data = model.model_dump(mode="json", by_alias=True)
    if "fixture" in data and data["fixture"] is None:
        del data["fixture"]
    return data


def _write(result: ExportResult, part: str, path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    size = path.stat().st_size
    result.files += 1
    result.bytes += size
    result.by_part[part] = result.by_part.get(part, 0) + size


def _rows(con: duckdb.DuckDBPyConnection, sql: str, *params: Any) -> list[dict[str, Any]]:
    cur = con.execute(sql, list(params))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


# -- work cards ---------------------------------------------------------------------------------


def build_cards(con: duckdb.DuckDBPyConnection) -> dict[str, m.WorkSummary]:
    """One short card per work, used wherever a work is listed (topic, author, venue, citations)."""
    names: dict[str, list[str]] = defaultdict(list)
    for r in _rows(
        con,
        "SELECT w.work_id, au.display_name FROM works w "
        "JOIN authorships a ON a.version_id = w.primary_version_id "
        "JOIN authors au ON au.author_id = a.author_id ORDER BY w.work_id, a.position",
    ):
        names[r["work_id"]].append(r["display_name"])
    cards: dict[str, m.WorkSummary] = {}
    for r in _rows(
        con,
        "SELECT w.work_id, w.title, w.year, COALESCE(w.cited_by_count, 0) AS cited, "
        "COALESCE(ve.acronym, '') AS acronym FROM works w "
        "LEFT JOIN versions v ON v.version_id = w.primary_version_id "
        "LEFT JOIN venues ve ON ve.venue_id = v.venue_id ORDER BY w.work_id",
    ):
        who = names[r["work_id"]]
        cards[r["work_id"]] = m.WorkSummary(
            work_id=r["work_id"],
            title=r["title"],
            year=int(r["year"]),
            venue_acronym=r["acronym"],
            authors=who[:CARD_AUTHORS],
            n_authors=len(who),
            cited_by_count=int(r["cited"]),
        )
    return cards


# -- topics -------------------------------------------------------------------------------------


def build_topics(con: duckdb.DuckDBPyConnection) -> list[m.Topic]:
    parents: dict[str, list[str]] = defaultdict(list)
    children: dict[str, list[str]] = defaultdict(list)
    for r in _rows(
        con,
        "SELECT src_topic, dst_topic FROM topic_edges WHERE edge_type = 'subtopic-of' "
        "ORDER BY dst_topic, src_topic",
    ):
        parents[r["src_topic"]].append(r["dst_topic"])
        children[r["dst_topic"]].append(r["src_topic"])
    summary = {
        r["topic_id"]: r
        for r in _rows(
            con,
            "SELECT topic_id, sum(papers)::INTEGER AS papers, sum(volume) AS volume, "
            "sum(n_low_confidence)::INTEGER AS low FROM agg_topic_year GROUP BY topic_id",
        )
    }
    out = []
    for t in _rows(
        con, "SELECT topic_id, name, description, level FROM topics ORDER BY level, topic_id"
    ):
        s = summary.get(t["topic_id"], {"papers": 0, "volume": 0.0, "low": 0})
        out.append(
            m.Topic(
                topic_id=t["topic_id"],
                name=t["name"],
                description=" ".join((t["description"] or "").split()),
                level=int(t["level"]),
                parents=sorted(parents[t["topic_id"]]),
                children=sorted(children[t["topic_id"]]),
                paper_count=int(s["papers"]),
                volume=round(float(s["volume"]), 3),
                n_low_confidence=int(s["low"]),
            )
        )
    return out


def build_topic_pages(
    con: duckdb.DuckDBPyConnection, topics: list[m.Topic], cards: dict[str, m.WorkSummary]
) -> list[m.TopicPage]:
    by_id = {t.topic_id: t for t in topics}
    edges: dict[str, dict[str, list[m.TopicEdge]]] = {t: {k: [] for k in LATERAL} for t in by_id}
    for r in _rows(
        con,
        "SELECT src_topic, dst_topic, edge_type, weight, confidence FROM topic_edges "
        "WHERE edge_type <> 'subtopic-of'",
    ):
        a, b, kind = r["src_topic"], r["dst_topic"], r["edge_type"]
        if a not in by_id or b not in by_id:
            continue
        w, c = round(float(r["weight"]), 4), round(float(r["confidence"]), 4)
        dirs = ("out", "in") if kind == "builds-on" else ("both", "both")
        for here, other, direction in ((a, b, dirs[0]), (b, a, dirs[1])):
            edges[here][kind].append(
                m.TopicEdge(
                    topic_id=other,
                    name=by_id[other].name,
                    edge_type=kind,
                    direction=direction,
                    weight=w,
                    confidence=c,
                )
            )
    papers: dict[str, list[m.TopicPaper]] = defaultdict(list)
    for r in _rows(
        con,
        "SELECT topic_id, work_id, confidence, low_confidence FROM agg_topic_work "
        f"WHERE rank <= {TOP_PAPERS} ORDER BY topic_id, rank",
    ):
        c = cards[r["work_id"]]
        papers[r["topic_id"]].append(
            m.TopicPaper(
                work_id=c.work_id,
                title=c.title,
                year=c.year,
                venue_acronym=c.venue_acronym,
                authors=c.authors,
                n_authors=c.n_authors,
                confidence=round(float(r["confidence"]), 4),
                cited_by_count=c.cited_by_count,
                low_confidence=bool(r["low_confidence"]),
            )
        )
    key_authors: dict[str, list[m.TopicAuthor]] = defaultdict(list)
    for r in _rows(
        con,
        "SELECT * FROM (SELECT a.topic_id, a.author_id, au.display_name, a.score, "
        "row_number() OVER (PARTITION BY a.topic_id ORDER BY a.score DESC, a.author_id) AS n "
        "FROM agg_topic_author a JOIN authors au ON au.author_id = a.author_id) "
        f"WHERE n <= {KEY_AUTHORS} ORDER BY topic_id, n",
    ):
        key_authors[r["topic_id"]].append(
            m.TopicAuthor(
                author_id=r["author_id"], name=r["display_name"], score=round(float(r["score"]), 3)
            )
        )
    series: dict[str, list[m.YearPoint]] = defaultdict(list)
    for r in _rows(
        con, "SELECT topic_id, year, papers, volume FROM agg_topic_year ORDER BY topic_id, year"
    ):
        series[r["topic_id"]].append(
            m.YearPoint(
                year=int(r["year"]), papers=int(r["papers"]), volume=round(float(r["volume"]), 3)
            )
        )

    def ref(t: str) -> m.TopicRef:
        return m.TopicRef(topic_id=t, name=by_id[t].name)

    def top(items: list[m.TopicEdge]) -> list[m.TopicEdge]:
        ordered = sorted(items, key=lambda e: (-e.weight, -e.confidence, e.topic_id, e.direction))
        return ordered[:EDGES_PER_TYPE]

    pages = []
    for t in topics:
        e = edges[t.topic_id]
        pages.append(
            m.TopicPage(
                topic=m.TopicSummary(**t.model_dump(include=set(m.TopicSummary.model_fields))),
                parents=[ref(p) for p in t.parents],
                children=[ref(c) for c in t.children],
                edges=m.TopicEdges(
                    related=top(e["related"]),
                    **{
                        "builds-on": top(e["builds-on"]),
                        "shared-community": top(e["shared-community"]),
                    },
                ),
                top_papers=papers[t.topic_id],
                key_authors=key_authors[t.topic_id],
                year_series=series[t.topic_id],
            )
        )
    return pages


# -- works, authors, venues ---------------------------------------------------------------------


def _links(r: dict[str, Any]) -> m.WorkLinks:
    return m.WorkLinks(
        dblp=f"https://dblp.org/rec/{r['dblp_key']}" if r["dblp_key"] else None,
        openalex=f"https://openalex.org/{r['openalex_id']}" if r["openalex_id"] else None,
        doi=f"https://doi.org/{r['doi']}" if r["doi"] else None,
        open_access=r["url_oa"],
    )


def build_works(
    con: duckdb.DuckDBPyConnection, topics: list[m.Topic], cards: dict[str, m.WorkSummary]
) -> list[m.Work]:
    names = {t.topic_id: t.name for t in topics}
    references: dict[str, list[m.WorkSummary]] = defaultdict(list)
    cited_by: dict[str, list[m.WorkSummary]] = defaultdict(list)
    for r in _rows(con, "SELECT DISTINCT citing_work_id, cited_work_id FROM citations"):
        if r["citing_work_id"] in cards and r["cited_work_id"] in cards:
            references[r["citing_work_id"]].append(cards[r["cited_work_id"]])
            cited_by[r["cited_work_id"]].append(cards[r["citing_work_id"]])

    def ranked(items: list[m.WorkSummary]) -> list[m.WorkSummary]:
        items = sorted(items, key=lambda c: (-c.cited_by_count, -c.year, c.work_id))
        return items[:RELATED_WORKS]

    versions: dict[str, list[m.WorkVersion]] = defaultdict(list)
    for r in _rows(
        con,
        "SELECT w.work_id, COALESCE(ve.acronym, '') AS acronym, COALESCE(v.year, w.year) AS year, "
        "v.volume, v.pages, v.doi, v.url_landing FROM works w "
        "JOIN versions v ON v.work_id = w.work_id LEFT JOIN venues ve ON ve.venue_id = v.venue_id "
        "ORDER BY w.work_id, (v.version_id = w.primary_version_id) DESC, v.year, v.version_id",
    ):
        versions[r["work_id"]].append(
            m.WorkVersion(
                venue_acronym=r["acronym"],
                year=int(r["year"]),
                volume=r["volume"],
                pages=r["pages"],
                doi=r["doi"],
                url=r["url_landing"] or (f"https://doi.org/{r['doi']}" if r["doi"] else None),
            )
        )
    tags: dict[str, list[m.Tag]] = defaultdict(list)
    for r in _rows(
        con,
        "SELECT work_id, topic_id, confidence, rank, is_primary, derived, provenance "
        "FROM work_topics ORDER BY work_id, derived, rank, topic_id",
    ):
        p = r["provenance"]
        tags[r["work_id"]].append(
            m.Tag(
                topic_id=r["topic_id"],
                topic_name=names[r["topic_id"]],
                confidence=round(float(r["confidence"]), 4),
                rank=int(r["rank"]),
                is_primary=bool(r["is_primary"]),
                derived=bool(r["derived"]),
                provenance=m.Provenance(
                    method=p["method"],
                    signals={
                        s["name"]: round(float(s["score"]), SIGNAL_DECIMALS)
                        for s in p["signals"] or []
                    },
                    tagger_version=p["tagger_version"],
                    taxonomy_version=str(p["taxonomy_version"]),
                    flags=list(p["flags"] or []),
                ),
            )
        )
    authors: dict[str, list[m.WorkAuthor]] = defaultdict(list)
    for r in _rows(
        con,
        "SELECT w.work_id, a.author_id, au.display_name, a.position FROM works w "
        "JOIN authorships a ON a.version_id = w.primary_version_id "
        "JOIN authors au ON au.author_id = a.author_id ORDER BY w.work_id, a.position",
    ):
        authors[r["work_id"]].append(
            m.WorkAuthor(
                author_id=r["author_id"], name=r["display_name"], position=int(r["position"])
            )
        )
    out = []
    for r in _rows(
        con,
        "SELECT w.work_id, w.title, w.year, w.work_type, COALESCE(w.cited_by_count, 0) AS cited, "
        "w.tag_status, v.doi, v.dblp_key, v.openalex_id, v.url_oa, v.venue_id, "
        "COALESCE(ve.acronym, '') AS acronym FROM works w "
        "LEFT JOIN versions v ON v.version_id = w.primary_version_id "
        "LEFT JOIN venues ve ON ve.venue_id = v.venue_id ORDER BY w.work_id",
    ):
        out.append(
            m.Work(
                work_id=r["work_id"],
                title=r["title"],
                year=int(r["year"]),
                work_type=r["work_type"],
                venue=m.WorkVenue(venue_id=r["venue_id"] or "", acronym=r["acronym"]),
                authors=authors[r["work_id"]],
                doi=r["doi"],
                links=_links(r),
                cited_by_count=int(r["cited"]),
                tag_status=r["tag_status"],
                tags=tags[r["work_id"]],
                versions=versions[r["work_id"]],
                references=ranked(references[r["work_id"]]),
                cited_by=ranked(cited_by[r["work_id"]]),
            )
        )
    return out


def build_authors(
    con: duckdb.DuckDBPyConnection, cards: dict[str, m.WorkSummary]
) -> list[m.Author]:
    topics: dict[str, list[m.AuthorTopic]] = defaultdict(list)
    for r in _rows(
        con,
        "SELECT * FROM (SELECT author_id, topic_id, score, row_number() OVER "
        "(PARTITION BY author_id ORDER BY score DESC, topic_id) AS n FROM agg_topic_author) "
        f"WHERE n <= {AUTHOR_TOPICS} ORDER BY author_id, n",
    ):
        topics[r["author_id"]].append(
            m.AuthorTopic(topic_id=r["topic_id"], score=round(float(r["score"]), 3))
        )
    work_ids: dict[str, list[str]] = defaultdict(list)
    for r in _rows(
        con,
        "SELECT DISTINCT a.author_id, v.work_id, w.year FROM authorships a "
        "JOIN versions v ON v.version_id = a.version_id JOIN works w ON w.work_id = v.work_id "
        "ORDER BY a.author_id, w.year DESC, v.work_id",
    ):
        work_ids[r["author_id"]].append(r["work_id"])
    coauthors: dict[str, list[m.Coauthor]] = defaultdict(list)
    for r in _rows(
        con,
        "WITH aw AS (SELECT DISTINCT a.author_id, v.work_id FROM authorships a "
        "JOIN versions v ON v.version_id = a.version_id) "
        "SELECT * FROM (SELECT x.author_id, y.author_id AS co, au.display_name AS name, "
        "count(*) AS n, row_number() OVER (PARTITION BY x.author_id "
        "ORDER BY count(*) DESC, au.display_name, y.author_id) AS k "
        "FROM aw x JOIN aw y ON y.work_id = x.work_id AND y.author_id <> x.author_id "
        "JOIN authors au ON au.author_id = y.author_id GROUP BY x.author_id, y.author_id, "
        f"au.display_name) WHERE k <= {COAUTHORS} ORDER BY author_id, k",
    ):
        coauthors[r["author_id"]].append(
            m.Coauthor(author_id=r["co"], name=r["name"], n_papers=int(r["n"]))
        )
    return [
        m.Author(
            author_id=r["author_id"],
            display_name=r["display_name"],
            name_variants=list(r["name_variants"] or []),
            dblp_pid=r["dblp_pid"],
            orcid=r["orcid"],
            topics=topics[r["author_id"]],
            work_ids=work_ids[r["author_id"]],
            papers=[cards[w] for w in work_ids[r["author_id"]] if w in cards],
            coauthors=coauthors[r["author_id"]],
        )
        for r in _rows(
            con,
            "SELECT author_id, display_name, name_variants, dblp_pid, orcid FROM authors "
            "ORDER BY author_id",
        )
    ]


def build_venues(con: duckdb.DuckDBPyConnection, cards: dict[str, m.WorkSummary]) -> list[m.Venue]:
    years: dict[str, list[m.VenueYear]] = defaultdict(list)
    n_works: dict[str, int] = defaultdict(int)
    by_venue: dict[str, list[m.WorkSummary]] = defaultdict(list)
    for r in _rows(
        con,
        "SELECT v.venue_id, w.work_id, w.year FROM works w "
        "JOIN versions v ON v.version_id = w.primary_version_id WHERE v.venue_id IS NOT NULL",
    ):
        n_works[r["venue_id"]] += 1
        by_venue[r["venue_id"]].append(cards[r["work_id"]])
    for venue_id, items in by_venue.items():
        counts: dict[int, int] = defaultdict(int)
        for c in items:
            counts[c.year] += 1
        years[venue_id] = [m.VenueYear(year=y, papers=n) for y, n in sorted(counts.items())]
    topics: dict[str, list[m.VenueTopic]] = defaultdict(list)
    for r in _rows(
        con,
        "SELECT * FROM (SELECT a.venue_id, a.topic_id, t.name, a.papers, row_number() OVER "
        "(PARTITION BY a.venue_id ORDER BY a.papers DESC, a.topic_id) AS n "
        "FROM agg_topic_venue a JOIN topics t ON t.topic_id = a.topic_id "
        f"WHERE t.level = 0 AND a.papers > 0) WHERE n <= {VENUE_TOPICS} ORDER BY venue_id, n",
    ):
        topics[r["venue_id"]].append(
            m.VenueTopic(topic_id=r["topic_id"], name=r["name"], papers=int(r["papers"]))
        )
    return [
        m.Venue(
            venue_id=r["venue_id"],
            acronym=r["acronym"],
            name=r["name"],
            kind=r["kind"],
            tier=r["tier"],
            first_year=int(r["first_year"]),
            last_year=None if r["last_year"] is None else int(r["last_year"]),
            successor_of=list(r["successor_of"] or []),
            homepage=r["homepage"],
            n_works=n_works[r["venue_id"]],
            year_series=years[r["venue_id"]],
            top_topics=topics[r["venue_id"]],
            top_papers=sorted(
                by_venue[r["venue_id"]], key=lambda c: (-c.cited_by_count, -c.year, c.work_id)
            )[:VENUE_TOP_PAPERS],
        )
        for r in _rows(
            con,
            "SELECT venue_id, acronym, name, kind, tier, first_year, last_year, successor_of, "
            "homepage FROM venues ORDER BY venue_id",
        )
    ]


def build_map(con: duckdb.DuckDBPyConnection) -> m.MapLayout:
    return m.MapLayout(
        nodes=[
            m.MapNode(
                topic_id=r["topic_id"],
                parent_id=r["parent_id"],
                level=int(r["level"]),
                x=float(r["x"]),
                y=float(r["y"]),
                r=float(r["r"]),
                ghost_parents=list(r["ghost_parents"] or []),
            )
            for r in _rows(
                con,
                "SELECT topic_id, parent_id, level, x, y, r, ghost_parents FROM agg_map_layout "
                "WHERE year IS NULL ORDER BY level, topic_id",
            )
        ]
    )


def build_search(
    con: duckdb.DuckDBPyConnection,
    authors: list[m.Author],
    venues: list[m.Venue],
    works: list[m.Work],
) -> m.SearchIndex:
    return m.SearchIndex(
        topics=[
            m.SearchTopic(topic_id=r["topic_id"], name=r["name"], aliases=list(r["aliases"] or []))
            for r in _rows(con, "SELECT topic_id, name, aliases FROM topics ORDER BY topic_id")
        ],
        authors=[m.SearchAuthor(author_id=a.author_id, name=a.display_name) for a in authors],
        venues=[m.SearchVenue(venue_id=v.venue_id, name=v.name, acronym=v.acronym) for v in venues],
        works=[m.SearchWork(work_id=w.work_id, title=w.title, year=w.year) for w in works],
    )


# -- the export ---------------------------------------------------------------------------------


def export_static(release: Path, out: Path) -> ExportResult:
    """Write the site data of ``release`` into ``out`` (the managed files are replaced)."""
    problems = release_build.verify(release)
    if problems:
        raise ExportError(f"{release} does not match its manifest: {problems}")
    manifest = json.loads((release / "manifest.json").read_text("utf-8"))
    con = _open(release)
    try:
        topics = build_topics(con)
        cards = build_cards(con)
        pages = build_topic_pages(con, topics, cards)
        works = build_works(con, topics, cards)
        authors = build_authors(con, cards)
        venues = build_venues(con, cards)
        layout = build_map(con)
        search = build_search(con, authors, venues, works)
    finally:
        con.close()
    info = m.DataInfo(
        release=manifest["version"],
        date=manifest["date"],
        tagger_version=manifest["tagger_version"],
        taxonomy_version=str(manifest["taxonomy_version"]),
        aggregate_version=manifest["aggregate_version"],
        works=len(works),
        works_by_tag_status={k: int(v) for k, v in manifest["works_by_tag_status"].items()},
        topics=len(topics),
        venues=[
            m.DataVenue(
                venue_id=v.venue_id,
                acronym=v.acronym,
                name=v.name,
                first_year=v.first_year,
                last_year=v.last_year,
                successor_of=v.successor_of,
            )
            for v in venues
        ],
        source_fetch_dates=manifest["source_fetch_dates"],
    )

    out.mkdir(parents=True, exist_ok=True)
    for name in MANAGED:
        target = out / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    result = ExportResult(out)
    _write(result, "topics", out / "topics.json", [_dump(t) for t in topics])
    for page in pages:
        _write(result, "topic", out / "topic" / f"{page.topic.topic_id}.json", _dump(page))
    for part, items, key in (
        ("works", works, lambda w: w.work_id),
        ("authors", authors, lambda a: a.author_id),
    ):
        shards: dict[str, dict[str, Any]] = defaultdict(dict)
        for item in items:
            shards[shard_of(key(item))][key(item)] = _dump(item)
        for shard, content in sorted(shards.items()):
            _write(result, part, out / part / f"{shard}.json", content)
    for venue in venues:
        _write(result, "venue", out / "venue" / f"{venue.venue_id}.json", _dump(venue))
    _write(result, "map", out / "map.json", _dump(layout))
    _write(result, "search", out / "search" / "index.json", _dump(search))
    _write(result, "meta", out / "meta.json", _dump(info))
    return result
