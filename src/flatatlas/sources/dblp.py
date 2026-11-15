"""Parse the DBLP dump into the ``stg_dblp_*`` staging tables (P1-01).

DBLP defines which papers belong to a venue (PLAN §3, §8.4), so this is the first stage that
produces rows. There is no network step: the dump is read with ``flatatlas.dblp_dump`` (D-49,
D-50). Pure and offline: ``parse_dump`` takes files and venues and returns plain rows;
``write_tables`` stores them.

* **Editions.** A ``proceedings`` record or a key that papers cite in ``crossref``. The edition's
  year is the key's last part (``conf/dlt/2019``), not the record's ``year`` (publication year).
  Two venues may share a stream (D-50): the edition year picks the venue. Editions that DBLP files
  outside the stream (``extra_editions``, DCFS 2009 and 2010 under CoRR) and keys that are not
  the venue's meetings (``excluded_editions``) come from ``config/venues.yaml`` (D-51).
* **Authors.** Paper records carry names only (homonyms as ``Name 0001``). The PID is the key of
  the person's ``<www key="homepages/...">`` record; a name is looked up among the names listed in
  those records (D-52). A name that no ``www`` record lists, or that two records list, gets no PID
  and is counted in the stats; nothing is guessed.
* **Front matter.** Rules live in ``config/dblp_parse.yaml``.
"""

from __future__ import annotations

import logging
import random
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import yaml

from flatatlas.db import write_parquet_atomic
from flatatlas.dblp_dump import (
    Record,
    edition_year,
    iter_records,
    md5_of,
    stream_of,
)
from flatatlas.settings import CONFIG_DIR, Paths
from flatatlas.venues import ExtraEdition, Venue

log = logging.getLogger(__name__)

RULES_FILE = CONFIG_DIR / "dblp_parse.yaml"
WWW_PREFIX = "homepages/"
TABLES = ("stg_dblp_edition", "stg_dblp_paper", "stg_dblp_authorship", "stg_dblp_author")

_DOI_URL = re.compile(r"^https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/\S+)$", re.IGNORECASE)
_ORCID = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])")
_ARXIV_DOI_PREFIX = "10.48550/arxiv."


# -- titles ---------------------------------------------------------------------------------------

_LATEX_ACCENT = re.compile(r"\\[\"'`^~=.]\s*\{?\\?([A-Za-z])\}?")
_LATEX_COMMAND = re.compile(r"\\[A-Za-z]+\*?")


def clean_title(title: str) -> str:
    """The title as shown: white space collapsed, DBLP's trailing period removed."""
    text = re.sub(r"\s+", " ", title).strip()
    if text.endswith(".") and not text.endswith(".."):
        text = text[:-1].rstrip()
    return text


def normalize_title(title: str) -> str:
    """Lowercase, no accents, no punctuation, no LaTeX fragments (PLAN §4.2 ``title_norm``)."""
    text = _LATEX_ACCENT.sub(r"\1", title)  # \"o, \'{e}, {\'\i} -> o, e
    text = _LATEX_COMMAND.sub(" ", text)  # \emph, \mathrm, \ell
    text = re.sub(r"[\\{}$^_]", "", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[\W_]+", " ", text.lower())
    return text.strip()


_HOMONYM_SUFFIX = re.compile(r"\s+\d{4}$")


def display_name(name: str) -> str:
    """``Bo Cui 0001`` -> ``Bo Cui``: DBLP's four-digit homonym suffix is not part of the name."""
    return _HOMONYM_SUFFIX.sub("", name)


# -- front matter ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class FrontMatterRules:
    titles: frozenset[str]
    patterns: tuple[re.Pattern[str], ...]
    if_no_pages: tuple[re.Pattern[str], ...]

    def classify(self, title: str, pages: str | None) -> str | None:
        """The rule that flags this record as front matter (for the audit column), or None."""
        norm = normalize_title(title)
        if norm in self.titles:
            return f"title:{norm}"
        for pattern in self.patterns:
            if pattern.search(norm):
                return f"pattern:{pattern.pattern}"
        if not (pages or "").strip():
            for pattern in self.if_no_pages:
                if pattern.search(norm):
                    return f"no-pages:{pattern.pattern}"
        return None


def parse_rules(raw: dict[str, Any]) -> FrontMatterRules:
    def compiled(name: str) -> tuple[re.Pattern[str], ...]:
        return tuple(re.compile(p) for p in raw.get(name) or [])

    return FrontMatterRules(
        titles=frozenset(normalize_title(t) for t in raw.get("front_matter_titles") or []),
        patterns=compiled("front_matter_patterns"),
        if_no_pages=compiled("front_matter_if_no_pages"),
    )


def load_rules(path: Path = RULES_FILE) -> FrontMatterRules:
    with path.open(encoding="utf-8") as handle:
        return parse_rules(yaml.safe_load(handle) or {})


# -- small field helpers --------------------------------------------------------------------------


def extract_dois(ee_values: Iterable[str]) -> list[str]:
    """DOIs found in ``ee`` links, lower-cased, in order, without duplicates."""
    seen: list[str] = []
    for value in ee_values:
        match = _DOI_URL.match(value.strip())
        if match and match.group(1).lower() not in seen:
            seen.append(match.group(1).lower())
    return seen


def preferred_doi(dois: Sequence[str]) -> str | None:
    """The publisher's DOI if there is one; an arXiv DOI only as a fallback."""
    for doi in dois:
        if not doi.startswith(_ARXIV_DOI_PREFIX):
            return doi
    return dois[0] if dois else None


def _int(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def _orcid(text: str | None) -> str | None:
    match = _ORCID.search(text or "")
    return match.group(1) if match else None


def orcid_of_person(record: Record) -> str | None:
    """ORCID of a ``www`` record: a ``note type="orcid"`` or a link to orcid.org."""
    for text, attrs in record.with_attrs("note"):
        if attrs.get("type") == "orcid" and (found := _orcid(text)):
            return found
    for text in record.fields.get("url", []):
        if "orcid.org" in text and (found := _orcid(text)):
            return found
    return None


# -- routing: which venue does an edition belong to ----------------------------------------------


class Router:
    """Maps DBLP streams, years and edition keys to venues."""

    def __init__(self, venues: Sequence[Venue]) -> None:
        self.venues = list(venues)
        self.by_stream: dict[str, list[Venue]] = defaultdict(list)
        self.extra: dict[str, tuple[Venue, ExtraEdition]] = {}
        self.excluded: dict[str, Venue] = {}
        for venue in venues:
            if venue.dblp_stream:
                self.by_stream[venue.dblp_stream].append(venue)
            for extra in venue.extra_editions:
                self.extra[extra.key] = (venue, extra)
            for key in venue.excluded_editions:
                self.excluded[key] = venue
        # Extra editions live in other streams (journals/corr); keep their papers findable.
        self.extra_streams = {stream_of(key) for key in self.extra}

    def wants_key(self, key: str) -> bool:
        return stream_of(key) in self.by_stream or stream_of(key) in self.extra_streams

    def venue_for(self, stream: str, year: int | None) -> Venue | None:
        for venue in self.by_stream.get(stream, []):
            if year is None:
                continue
            if venue.first_year is not None and year < venue.first_year:
                continue
            if venue.last_year is not None and year > venue.last_year:
                continue
            return venue
        return None

    def route_edition(self, key: str, fallback_year: int | None) -> tuple[Venue, int] | None:
        """``(venue, edition year)`` for an edition key, or None if it is nobody's edition."""
        if key in self.extra:
            venue, extra = self.extra[key]
            return venue, extra.year
        year = edition_year(key, fallback_year)
        venue = self.venue_for(stream_of(key), year)
        return (venue, year) if venue is not None and year is not None else None


# -- the parse ------------------------------------------------------------------------------------


@dataclass
class ParsedDblp:
    editions: list[dict[str, Any]] = field(default_factory=list)
    papers: list[dict[str, Any]] = field(default_factory=list)
    authorships: list[dict[str, Any]] = field(default_factory=list)
    authors: list[dict[str, Any]] = field(default_factory=list)
    stats: Counter[str] = field(default_factory=Counter)
    notes: dict[str, Any] = field(default_factory=dict)  # lists of examples, ordering, newest mdate


def _www_names(record: Record) -> list[str]:
    return record.fields.get("author", [])


def parse_dump(
    dump_path: Path,
    dtd_path: Path,
    venues: Sequence[Venue],
    rules: FrontMatterRules,
    *,
    progress: Callable[[int], None] | None = None,
) -> ParsedDblp:
    """Read the dump once (twice if DBLP ever puts person records before the papers)."""
    router = Router(venues)
    result = ParsedDblp()
    stats = result.stats

    proceedings: dict[str, Record] = {}
    papers: list[Record] = []
    names: set[str] = set()
    www: dict[str, Record] = {}  # pid -> person record, only people named on a kept paper
    www_started = False
    late_papers = False
    newest = ""

    def keep_www(record: Record, wanted: set[str]) -> None:
        if any(name in wanted for name in _www_names(record)):
            www[record.key[len(WWW_PREFIX) :]] = record

    def want(key: str) -> bool:
        return key.startswith(WWW_PREFIX) or router.wants_key(key)

    for record in iter_records(dump_path, dtd_path, key_filter=want, progress=progress):
        if record.key.startswith(WWW_PREFIX):
            www_started = True
            keep_www(record, names)
            continue
        if record.tag == "proceedings":
            relevant = record.key in router.extra or stream_of(record.key) in router.by_stream
            if relevant:
                proceedings[record.key] = record
        elif stream_of(record.key) in router.by_stream or record.first("crossref") in router.extra:
            papers.append(record)
            names.update(record.fields.get("author", []))
            relevant = True
        else:
            relevant = False  # another record of an extra stream (CoRR): not ours
        if relevant:
            newest = max(newest, record.mdate or "")
            late_papers = late_papers or www_started

    if late_papers:  # not the case in the 2026 dump; kept so a change of order cannot go unseen
        log.warning("person records come before the papers: second pass over the dump")
        www.clear()
        for record in iter_records(
            dump_path, dtd_path, key_filter=lambda k: k.startswith(WWW_PREFIX), progress=progress
        ):
            keep_www(record, names)
    result.notes["second_pass"] = late_papers
    result.notes["newest_mdate"] = newest

    # -- people ----------------------------------------------------------------------------------
    pid_of: dict[str, str | None] = {}
    for pid, person in sorted(www.items()):
        for name in _www_names(person):
            pid_of[name] = None if name in pid_of and pid_of[name] != pid else pid
    ambiguous = sorted(n for n, pid in pid_of.items() if pid is None)
    result.notes["ambiguous_names"] = ambiguous[:20]
    stats["names_ambiguous"] = len(ambiguous)

    # -- editions --------------------------------------------------------------------------------
    cited: dict[str, Counter[int]] = defaultdict(Counter)
    for paper in papers:
        ref = paper.first("crossref")
        if ref and (year := _int(paper.first("year"))):
            cited[ref][year] += 1

    edition_rows: dict[str, dict[str, Any]] = {}
    for key in sorted({*proceedings, *cited} | set(router.extra)):
        in_scope = key in router.extra or stream_of(key) in router.by_stream
        if not in_scope:
            continue  # a crossref into another stream
        if key in router.excluded:
            stats["editions_excluded"] += 1
            continue
        record = proceedings.get(key)
        published = _int(record.first("year")) if record else None
        if published is None and cited.get(key):
            published = cited[key].most_common(1)[0][0]
        routed = router.route_edition(key, published)
        if routed is None:
            stats["editions_unassigned"] += 1
            result.notes.setdefault("unassigned_editions", []).append(key)
            continue
        venue, year = routed
        dois = extract_dois(record.fields.get("ee", [])) if record else []
        edition_rows[key] = {
            "edition_key": key,
            "venue_id": venue.id,
            "year": year,
            "published_year": published,
            "label": f"{venue.acronym} {year}",
            "title": clean_title(record.first("title") or "") if record else None,
            "booktitle": record.first("booktitle") if record else None,
            "publisher": record.first("publisher") if record else None,
            "series": record.first("series") if record else None,
            "volume": record.first("volume") if record else None,
            "proceedings_doi": preferred_doi(dois),
            "isbns": record.fields.get("isbn", []) if record else [],
            "has_proceedings_record": record is not None,
            "source": "extra" if key in router.extra else "stream",
            "n_papers": 0,
            "mdate": record.mdate if record else None,
        }
    stats["editions"] = len(edition_rows)

    # -- papers and authorships ------------------------------------------------------------------
    paper_orcid: dict[str, str] = {}
    for record in papers:
        ref = record.first("crossref")
        title = record.first("title") or ""
        pages = record.first("pages")
        year = _int(record.first("year"))
        if ref and ref in router.excluded:
            stats["papers_excluded"] += 1
            continue
        if ref in edition_rows:
            edition = edition_rows[ref]
            venue_id, edition_key, e_year = edition["venue_id"], ref, edition["year"]
        elif ref is None and (venue := router.venue_for(stream_of(record.key), year)):
            venue_id, edition_key, e_year = venue.id, None, None  # no crossref: venue by year
            stats["papers_without_edition"] += 1
        else:
            stats["papers_unassigned"] += 1
            result.notes.setdefault("unassigned_papers", []).append(record.key)
            continue
        if edition_key is not None:
            edition_rows[edition_key]["n_papers"] += 1
        dois = extract_dois(record.fields.get("ee", []))
        rule = rules.classify(title, pages)
        result.papers.append(
            {
                "dblp_key": record.key,
                "venue_id": venue_id,
                "edition_key": edition_key,
                "edition_year": e_year,
                "year": year,
                "title": clean_title(title),
                "title_norm": normalize_title(title),
                "pages": pages,
                "doi": preferred_doi(dois),
                "dois": dois,
                "ee_urls": [u for u in record.fields.get("ee", []) if not _DOI_URL.match(u)],
                "type": record.tag,
                "is_front_matter": rule is not None,
                "front_matter_rule": rule,
                "mdate": record.mdate,
            }
        )
        for position, (name, attrs) in enumerate(record.with_attrs("author"), start=1):
            if attrs.get("orcid") and (found := _orcid(attrs["orcid"])):
                paper_orcid.setdefault(name, found)
            result.authorships.append(
                {
                    "dblp_key": record.key,
                    "position": position,
                    "pid": pid_of.get(name),
                    "name_raw": name,
                    "orcid": _orcid(attrs.get("orcid")),
                }
            )

    result.editions = sorted(edition_rows.values(), key=lambda e: (e["venue_id"], e["edition_key"]))
    result.papers.sort(key=lambda p: p["dblp_key"])
    stats["papers"] = len(result.papers)
    stats["papers_front_matter"] = sum(p["is_front_matter"] for p in result.papers)
    stats["authorships"] = len(result.authorships)

    # -- authors ---------------------------------------------------------------------------------
    used_pids = {a["pid"] for a in result.authorships if a["pid"]}
    papers_of: dict[str, set[str]] = defaultdict(set)
    for row in result.authorships:
        if row["pid"]:
            papers_of[row["pid"]].add(row["dblp_key"])
    for pid in sorted(used_pids):
        person = www[pid]
        variants = _www_names(person)
        orcid_www = orcid_of_person(person)
        orcid_paper = next((paper_orcid[n] for n in variants if n in paper_orcid), None)
        if orcid_www and orcid_paper and orcid_www != orcid_paper:
            stats["orcid_conflicts"] += 1
        result.authors.append(
            {
                "pid": pid,
                "name": display_name(variants[0]),
                "name_variants": variants,
                "orcid": orcid_www or orcid_paper,
                "n_papers": len(papers_of[pid]),
                "mdate": person.mdate,
            }
        )
    unmatched = sorted({a["name_raw"] for a in result.authorships if a["pid"] is None})
    stats["authors"] = len(result.authors)
    stats["names_without_pid"] = len(unmatched)
    stats["authorships_without_pid"] = sum(1 for a in result.authorships if a["pid"] is None)
    result.notes["names_without_pid"] = unmatched[:20]
    return result


# -- checks and reports ---------------------------------------------------------------------------


def compare_with_index(
    parsed: ParsedDblp, index: dict[str, Any] | None, venues: Sequence[Venue]
) -> list[dict[str, Any]]:
    """Per edition: papers parsed here against papers counted by ``venues scan-dump``.

    The index counts every record that cites the edition in ``crossref``; the two numbers must be
    equal. Extra editions (outside the indexed streams) and excluded ones are not in the index.
    Returns one row per edition with a ``status``: ``ok``, ``differs`` or ``not indexed``.
    """
    in_index: dict[str, int] = {}
    if index:
        for info in index.get("streams", {}).values():
            for edition in info["editions"]:
                in_index[edition["key"]] = edition["n_papers"]
    rows = []
    for edition in parsed.editions:
        key = edition["edition_key"]
        if key not in in_index:
            rows.append({**_brief(edition), "indexed": None, "status": "not indexed"})
            continue
        status = "ok" if in_index[key] == edition["n_papers"] else "differs"
        rows.append({**_brief(edition), "indexed": in_index[key], "status": status})
    return rows


def _brief(edition: dict[str, Any]) -> dict[str, Any]:
    return {
        "venue_id": edition["venue_id"],
        "edition_key": edition["edition_key"],
        "year": edition["year"],
        "parsed": edition["n_papers"],
    }


def sample_rows(parsed: ParsedDblp, n: int = 10, seed: int = 20261115) -> list[dict[str, Any]]:
    """``n`` random papers with their authors (printed names and PIDs), for eyeballing."""
    by_paper: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in parsed.authorships:
        by_paper[row["dblp_key"]].append(row)
    rng = random.Random(seed)
    chosen = rng.sample(parsed.papers, min(n, len(parsed.papers)))
    return [
        {**paper, "authors": sorted(by_paper[paper["dblp_key"]], key=lambda a: a["position"])}
        for paper in chosen
    ]


# -- storage --------------------------------------------------------------------------------------

_SCHEMAS: dict[str, pa.Schema] = {
    "stg_dblp_edition": pa.schema(
        [
            ("edition_key", pa.string()),
            ("venue_id", pa.string()),
            ("year", pa.int16()),
            ("published_year", pa.int16()),
            ("label", pa.string()),
            ("title", pa.string()),
            ("booktitle", pa.string()),
            ("publisher", pa.string()),
            ("series", pa.string()),
            ("volume", pa.string()),
            ("proceedings_doi", pa.string()),
            ("isbns", pa.list_(pa.string())),
            ("has_proceedings_record", pa.bool_()),
            ("source", pa.string()),
            ("n_papers", pa.int32()),
            ("mdate", pa.string()),
        ]
    ),
    "stg_dblp_paper": pa.schema(
        [
            ("dblp_key", pa.string()),
            ("venue_id", pa.string()),
            ("edition_key", pa.string()),
            ("edition_year", pa.int16()),
            ("year", pa.int16()),
            ("title", pa.string()),
            ("title_norm", pa.string()),
            ("pages", pa.string()),
            ("doi", pa.string()),
            ("dois", pa.list_(pa.string())),
            ("ee_urls", pa.list_(pa.string())),
            ("type", pa.string()),
            ("is_front_matter", pa.bool_()),
            ("front_matter_rule", pa.string()),
            ("mdate", pa.string()),
        ]
    ),
    "stg_dblp_authorship": pa.schema(
        [
            ("dblp_key", pa.string()),
            ("position", pa.int16()),
            ("pid", pa.string()),
            ("name_raw", pa.string()),
            ("orcid", pa.string()),
        ]
    ),
    "stg_dblp_author": pa.schema(
        [
            ("pid", pa.string()),
            ("name", pa.string()),
            ("name_variants", pa.list_(pa.string())),
            ("orcid", pa.string()),
            ("n_papers", pa.int32()),
            ("mdate", pa.string()),
        ]
    ),
}


def to_arrow(parsed: ParsedDblp) -> dict[str, pa.Table]:
    rows = {
        "stg_dblp_edition": parsed.editions,
        "stg_dblp_paper": parsed.papers,
        "stg_dblp_authorship": parsed.authorships,
        "stg_dblp_author": parsed.authors,
    }
    return {
        name: pa.Table.from_pylist(rows[name], schema=schema) for name, schema in _SCHEMAS.items()
    }


def write_tables(con: duckdb.DuckDBPyConnection, paths: Paths, parsed: ParsedDblp) -> list[Path]:
    """Replace the four staging tables in the warehouse and write a Parquet copy of each.

    The tables hold the venues of the last run; a run with ``--venue`` replaces all four.
    """
    written = []
    for name, table in to_arrow(parsed).items():
        con.register("_stage_rows", table)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _stage_rows")
        con.unregister("_stage_rows")
        written.append(write_parquet_atomic(table, paths.warehouse / "staging" / f"{name}.parquet"))
    return written


def dump_facts(dump_path: Path, md5: str | None = None) -> dict[str, str]:
    """What identifies the dump in ``ops_run_log``: MD5, file date, size."""
    stat = dump_path.stat()
    return {
        "dump_md5": md5 or md5_of(dump_path),
        "dump_file_date": datetime.fromtimestamp(stat.st_mtime, UTC).date().isoformat(),
        "dump_bytes": str(stat.st_size),
    }


def doi_share(parsed: ParsedDblp) -> list[dict[str, Any]]:
    """Share of papers (front matter left out) with a DOI, per venue and decade of the edition."""
    totals: Counter[tuple[str, int]] = Counter()
    with_doi: Counter[tuple[str, int]] = Counter()
    for paper in parsed.papers:
        year = paper["edition_year"] or paper["year"]
        if paper["is_front_matter"] or year is None:
            continue
        key = (paper["venue_id"], year // 10 * 10)
        totals[key] += 1
        with_doi[key] += 1 if paper["doi"] else 0
    return [
        {
            "venue_id": venue,
            "decade": decade,
            "papers": totals[(venue, decade)],
            "with_doi": with_doi[(venue, decade)],
            "share": with_doi[(venue, decade)] / totals[(venue, decade)],
        }
        for venue, decade in sorted(totals)
    ]


def select_venues(registry: Any, active: Sequence[str] | str, requested: str | None) -> list[Venue]:
    """The venues to parse: the requested one or the profile's, plus their predecessors.

    A venue whose ``verified.dblp`` is empty is refused (D-48). Raises ``KeyError`` for an
    unknown venue and ``ValueError`` for an unverified one.
    """
    wanted = [requested] if requested else (registry.ids() if active == "all" else list(active))
    ids: list[str] = []
    for venue_id in wanted:
        for item in (venue_id, *registry.predecessors(venue_id)):  # KeyError if unknown
            if item not in ids:
                ids.append(item)
    chosen = [registry.get(i) for i in registry.ids() if i in ids]
    unverified = [v.id for v in chosen if v.verified.dblp is None]
    if unverified:
        raise ValueError(f"not verified against DBLP (D-48): {', '.join(unverified)}")
    return chosen
