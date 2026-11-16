"""Crossref enrichment for the DOIs OpenAlex does not fully cover (P1-02).

Crossref is the second choice (PLAN §5.2 step 4): only DOIs that OpenAlex does not have, or has
without pages, a date, a reference list or an abstract. One call per DOI (``/works/<doi>``) in the
polite pool (``mailto`` is added by ``SourceClient``). A DOI that Crossref does not know answers
404, which the client caches, so it is asked only once.

Abstracts arrive as JATS XML. They are stripped to plain text and go to ``local_abstract`` only
(CLAUDE.md rule 2).
"""

from __future__ import annotations

import html
import logging
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import duckdb
import pyarrow as pa

from flatatlas.db import replace_table
from flatatlas.harvest import Page, paged
from flatatlas.http import SourceClient
from flatatlas.settings import Paths
from flatatlas.sources.openalex import _job_key, write_local_abstracts

log = logging.getLogger(__name__)

SOURCE = "crossref"
PARSER_VERSION = "crossref-parse/1"
PAGE_SIZE = 50  # DOIs per cursor step: the cursor is saved after each
# arXiv DOIs are registered with DataCite, not Crossref: asking would only produce 404s.
NOT_CROSSREF_PREFIXES = ("10.48550/",)
TABLES = ("stg_crossref_work",)


# -- which DOIs to ask ---------------------------------------------------------------------------

NEEDS_SQL = """
SELECT DISTINCT p.doi
FROM stg_dblp_paper p
LEFT JOIN stg_openalex_lookup l ON l.dblp_key = p.dblp_key
LEFT JOIN stg_openalex_work w ON w.openalex_id = l.openalex_id
WHERE p.doi IS NOT NULL AND NOT p.is_front_matter
  AND ({venue_clause})
  AND (
        w.openalex_id IS NULL
     OR NOT coalesce(w.has_abstract, false)
     OR w.first_page IS NULL
     OR w.publication_date IS NULL
     OR coalesce(w.n_references_listed, 0) = 0
  )
ORDER BY {order}
"""


def is_crossref_doi(doi: str) -> bool:
    return not doi.lower().startswith(NOT_CROSSREF_PREFIXES)


def dois_needing_crossref(
    con: duckdb.DuckDBPyConnection,
    *,
    venue_ids: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[str]:
    """DOIs missing in OpenAlex or lacking pages, date, references or abstract there.

    Needs ``stg_openalex_lookup`` and ``stg_openalex_work`` (run ``parse openalex`` first).
    With ``limit`` the order is a hash of the DOI, so a small run is a mixed sample.
    """
    clause, args = "true", []
    if venue_ids:
        clause = f"p.venue_id IN ({', '.join('?' * len(venue_ids))})"
        args = list(venue_ids)
    order = "hash(p.doi || 'p1-02-crossref'), p.doi" if limit else "p.doi"
    sql = NEEDS_SQL.format(venue_clause=clause, order=order)
    if limit:
        sql += f" LIMIT {int(limit)}"
    dois = [r[0].lower() for r in con.execute(sql, args).fetchall()]
    return [d for d in dois if is_crossref_doi(d)]


# -- harvest -------------------------------------------------------------------------------------


@dataclass
class HarvestStats:
    asked: int = 0
    from_cache: int = 0
    found: int = 0
    not_found: int = 0

    def as_counts(self) -> dict[str, int]:
        return {
            "dois_asked": self.asked,
            "dois_from_cache": self.from_cache,
            "dois_found": self.found,
            "dois_not_found": self.not_found,
        }


def work_path(doi: str) -> str:
    return f"/works/{doi}"


def harvest(
    con: duckdb.DuckDBPyConnection,
    client: SourceClient,
    dois: Sequence[str],
    *,
    restart: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> HarvestStats:
    """Fetch ``/works/<doi>`` for each DOI. Resumable; the cache makes a repeat free."""
    stats = HarvestStats()
    say = on_progress or (lambda _msg: None)
    ordered = sorted(set(dois))
    if not ordered:
        return stats
    job = _job_key("works-by-doi", ordered)

    def fetch_page(cursor: str | None) -> Page:
        start = int(cursor or 0)
        chunk = ordered[start : start + PAGE_SIZE]
        for doi in chunk:
            resp = client.get(work_path(doi))
            stats.asked += 1
            stats.from_cache += resp.from_cache
            if resp.data is None:
                stats.not_found += 1
            else:
                stats.found += 1
        end = start + len(chunk)
        say(f"crossref {end}/{len(ordered)} DOIs ({stats.not_found} not found)")
        return Page(items=chunk, next_cursor=str(end) if end < len(ordered) else None)

    for _page in paged(con, SOURCE, job, fetch_page, restart=restart):
        pass
    return stats


# -- JATS and dates ------------------------------------------------------------------------------

_TITLE_ELEMENT = re.compile(r"<(?:jats:)?title\b[^>]*>(.*?)</(?:jats:)?title>", re.I | re.S)
_BLOCK_END = re.compile(r"</(?:jats:)?(?:p|sec|title|list-item|abstract)>", re.I)
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


def strip_jats(xml: str | None) -> str | None:
    """Plain text of a Crossref JATS abstract.

    A heading that only says "Abstract" is dropped; other section titles stay as plain text.
    Entities are decoded after the tags are gone, so ``&lt;`` in the text stays a ``<``.
    """
    if not xml:
        return None

    def drop_abstract_heading(match: re.Match[str]) -> str:
        return "" if _TAG.sub("", match.group(1)).strip().lower() == "abstract" else match.group(0)

    text = _TITLE_ELEMENT.sub(drop_abstract_heading, xml)
    text = _BLOCK_END.sub(" ", text)
    text = _TAG.sub("", text)
    text = _SPACES.sub(" ", html.unescape(text)).strip()
    return text or None


def date_from_parts(block: dict[str, Any] | None) -> str | None:
    """``{"date-parts": [[2019, 3]]}`` -> ``2019-03``; a missing or null year gives None."""
    try:
        parts = (block or {})["date-parts"][0]
    except (KeyError, IndexError, TypeError):
        return None
    if not parts or parts[0] is None:
        return None
    return "-".join([f"{parts[0]:04d}"] + [f"{p:02d}" for p in parts[1:3] if p is not None])


def parse_message(msg: dict[str, Any], fetched_at: str | None = None) -> tuple[dict, str | None]:
    """One Crossref ``message`` -> (``stg_crossref_work`` row, abstract text or None)."""
    abstract = strip_jats(msg.get("abstract"))
    page = msg.get("page")
    refs = msg.get("reference") or []
    title = (msg.get("title") or [None])[0]
    containers = msg.get("container-title") or []
    issued = date_from_parts(msg.get("issued"))
    row = {
        "doi": (msg.get("DOI") or "").lower() or None,
        "crossref_type": msg.get("type"),
        "title": title,
        # Springer lists the series first and the proceedings second ("LNCS", "Developments in ...")
        "container_titles": list(containers),
        "publisher": msg.get("publisher"),
        "volume": msg.get("volume"),
        "issue": msg.get("issue"),
        "page": page,
        "first_page": page.split("-")[0].strip() if page else None,
        "issued": issued,
        "issued_year": int(issued[:4]) if issued else None,
        "published_print": date_from_parts(msg.get("published-print")),
        "published_online": date_from_parts(msg.get("published-online")),
        "reference_count": msg.get("reference-count"),
        "n_references_listed": len(refs),
        "is_referenced_by_count": msg.get("is-referenced-by-count"),
        "issn": list(msg.get("ISSN") or []),
        "isbn": list(msg.get("ISBN") or []),
        "language": msg.get("language"),
        "has_abstract": abstract is not None,
        "abstract_chars": len(abstract) if abstract else None,
        "fetched_at": fetched_at,
        "parser_version": PARSER_VERSION,
    }
    return row, abstract


# -- parse ---------------------------------------------------------------------------------------


@dataclass
class ParsedCrossref:
    works: list[dict[str, Any]] = field(default_factory=list)
    abstracts: list[dict[str, Any]] = field(default_factory=list)
    stats: Counter = field(default_factory=Counter)


def parse_crossref(client: SourceClient, papers: Sequence[tuple[str, str]]) -> ParsedCrossref:
    """``papers`` are ``(dblp_key, doi)`` pairs. Reads the cache only; no network."""
    out = ParsedCrossref()
    done: dict[str, str | None] = {}  # doi -> abstract (so a DOI shared by two papers parses once)
    for dblp_key, doi in papers:
        doi = doi.lower()
        if not is_crossref_doi(doi):
            out.stats["skipped_not_crossref"] += 1
            continue
        if doi not in done:
            resp = client.cached(work_path(doi))
            if resp is None:
                out.stats["not_fetched"] += 1
                continue
            if resp.data is None or not isinstance(resp.data, dict) or "message" not in resp.data:
                out.stats["not_found"] += 1
                done[doi] = None
                continue
            row, abstract = parse_message(resp.data["message"], resp.fetched_at.isoformat())
            row["doi"] = row["doi"] or doi
            out.works.append(row)
            out.stats["found"] += 1
            done[doi] = abstract
        abstract = done[doi]
        if abstract:
            out.abstracts.append(
                {
                    "dblp_key": dblp_key,
                    "openalex_id": None,
                    "doi": doi,
                    "source": SOURCE,
                    "text": abstract,
                    "n_chars": len(abstract),
                }
            )
    out.stats["abstracts"] = len(out.abstracts)
    return out


# -- storage -------------------------------------------------------------------------------------

_S = pa.string()
SCHEMA = pa.schema(
    [
        ("doi", _S),
        ("crossref_type", _S),
        ("title", _S),
        ("container_titles", pa.list_(_S)),
        ("publisher", _S),
        ("volume", _S),
        ("issue", _S),
        ("page", _S),
        ("first_page", _S),
        ("issued", _S),
        ("issued_year", pa.int16()),
        ("published_print", _S),
        ("published_online", _S),
        ("reference_count", pa.int32()),
        ("n_references_listed", pa.int32()),
        ("is_referenced_by_count", pa.int32()),
        ("issn", pa.list_(_S)),
        ("isbn", pa.list_(_S)),
        ("language", _S),
        ("has_abstract", pa.bool_()),
        ("abstract_chars", pa.int32()),
        ("fetched_at", _S),
        ("parser_version", _S),
    ]
)


def write_tables(con: duckdb.DuckDBPyConnection, paths: Paths, parsed: ParsedCrossref) -> None:
    table = pa.Table.from_pylist(parsed.works, schema=SCHEMA)
    replace_table(
        con, "stg_crossref_work", table, paths.warehouse / "staging" / "stg_crossref_work.parquet"
    )
    write_local_abstracts(con, paths, SOURCE, parsed.abstracts)
