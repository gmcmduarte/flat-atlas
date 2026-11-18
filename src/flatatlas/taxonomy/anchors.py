"""Verifying the anchor papers of ``taxonomy/anchors.yaml`` against the sources (PLAN §9.6).

An anchor is only useful if its identifier names the paper it claims to name. This module checks
that, and says whether each anchor is in the corpus:

* a **DOI** is looked up in OpenAlex by ID (free, cached by ``SourceClient``); the title found
  must match the anchor's title and the year must be close;
* a **DBLP key** is found in the warehouse (pilot papers) or, for keys outside it, in the local
  DBLP dump (one streaming pass, about two minutes; the DBLP API is not used, D-49);
* **in the corpus** means a ``core_version`` row carries the anchor's DOI or DBLP key.

``find_by_title`` proposes identifiers for anchors that have none yet: a title match in the DBLP
dump first, then a capped OpenAlex title search (USD 0.001 a call). It only prints candidates;
the human-edited file is never rewritten (CLAUDE.md rule 5).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from flatatlas.dblp_dump import iter_records
from flatatlas.http import SourceClient
from flatatlas.resolve.text import title_key, title_similarity
from flatatlas.sources.dblp import extract_dois, normalize_title, preferred_doi
from flatatlas.taxonomy.schema import AnchorEntry

TITLE_MIN = 0.85  # anchor title against the source's title (token-sort ratio after folding)
YEAR_SLACK = 1  # conference and journal years of one work often differ by one
SELECT = "id,doi,title,publication_year"
SEARCH_COST_USD = 0.001  # OpenAlex ``search`` cost kind (config/sources.yaml)
PUBLICATION_TAGS = frozenset({"article", "inproceedings", "incollection", "book"})
_NOT_QUERY_CHARS = re.compile(r"[^\w\s-]+")


@dataclass(frozen=True)
class Found:
    """A record a source returned for an identifier or a title."""

    source: str  # openalex | dblp-dump | warehouse
    title: str
    year: int | None
    doi: str | None = None
    dblp: str | None = None


@dataclass
class AnchorStatus:
    anchor: AnchorEntry
    verified: list[str] = field(default_factory=list)  # "doi (openalex, 0.98)"
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # reported, not failures
    work_id: str | None = None

    @property
    def ok(self) -> bool:
        return not self.problems and bool(self.verified)


# -- the corpus -----------------------------------------------------------------------------------


@dataclass
class Corpus:
    """DOIs and DBLP keys of the corpus versions, with the work each belongs to."""

    by_doi: dict[str, str] = field(default_factory=dict)
    by_dblp: dict[str, str] = field(default_factory=dict)
    dblp_records: dict[str, Found] = field(default_factory=dict)

    def work_of(self, anchor: AnchorEntry) -> str | None:
        if anchor.dblp and anchor.dblp in self.by_dblp:
            return self.by_dblp[anchor.dblp]
        if anchor.doi and anchor.doi in self.by_doi:
            return self.by_doi[anchor.doi]
        return None


def load_corpus(con: duckdb.DuckDBPyConnection | None) -> Corpus:
    corpus = Corpus()
    if con is None:
        return corpus
    rows = con.execute(
        "SELECT v.doi, v.dblp_key, v.work_id, w.title, v.year "
        "FROM core_version v JOIN core_work w USING (work_id)"
    ).fetchall()
    for doi, key, work_id, title, year in rows:
        if doi:
            corpus.by_doi[doi.lower()] = work_id
        if key:
            corpus.by_dblp[key] = work_id
            corpus.dblp_records[key] = Found("warehouse", title, year, doi, key)
    return corpus


# -- sources --------------------------------------------------------------------------------------


def lookup_doi(client: SourceClient, doi: str, *, offline: bool = False) -> Found | None | str:
    """The OpenAlex record of a DOI, None if OpenAlex does not hold it, or ``"uncached"`` when
    ``offline`` and the answer is not in the cache."""
    path, params = f"/works/doi:{doi}", {"select": SELECT}
    resp = client.cached(path, params) if offline else client.get(path, params, cost="singleton")
    if resp is None:
        return "uncached"
    if resp.data is None:
        return None
    return _found_from_openalex(resp.data)


def _found_from_openalex(work: Mapping[str, Any]) -> Found:
    doi = work.get("doi")
    if doi:
        doi = doi.lower().removeprefix("https://doi.org/")
    return Found("openalex", work.get("title") or "", work.get("publication_year"), doi)


def _record_found(record) -> Found:
    year = record.first("year")
    return Found(
        "dblp-dump",
        record.first("title") or "",
        int(year) if year and year.isdigit() else None,
        preferred_doi(extract_dois(record.fields.get("ee", []))),
        record.key,
    )


def scan_dump(
    dump: Path,
    dtd: Path,
    *,
    keys: Iterable[str] = (),
    titles: Iterable[str] = (),
    progress: Callable[[int], None] | None = None,
) -> tuple[dict[str, Found], dict[str, list[Found]]]:
    """One pass over the dump: records by key, and records whose normalised title is wanted."""
    wanted_keys = frozenset(keys)
    wanted_titles = frozenset(normalize_title(t) for t in titles)
    by_key: dict[str, Found] = {}
    by_title: dict[str, list[Found]] = {}
    key_filter = (lambda k: k in wanted_keys) if not wanted_titles else None
    for record in iter_records(dump, dtd, key_filter=key_filter, progress=progress):
        if record.key in wanted_keys:
            by_key[record.key] = _record_found(record)
        if wanted_titles and record.tag in PUBLICATION_TAGS:
            norm = normalize_title(record.first("title") or "")
            if norm in wanted_titles:
                by_title.setdefault(norm, []).append(_record_found(record))
    return by_key, by_title


def title_search_params(title: str, year: int) -> dict[str, Any]:
    query = re.sub(r"\s+", " ", _NOT_QUERY_CHARS.sub(" ", title)).strip()
    years = "|".join(str(year + d) for d in range(-YEAR_SLACK, YEAR_SLACK + 1))
    return {"filter": f"title.search:{query},publication_year:{years}", "per_page": 5,
            "select": SELECT}  # fmt: skip


def search_title(client: SourceClient, title: str, year: int) -> list[Found]:
    resp = client.get("/works", title_search_params(title, year), cost="search")
    results = (resp.data or {}).get("results", [])
    return [_found_from_openalex(w) for w in results]


# -- verification ---------------------------------------------------------------------------------


def title_match(anchor_title: str, found_title: str) -> float:
    """Token-sort similarity, or 1.0 when one folded title of at least three words contains the
    other whole and is at least half its length (journals prefix section names:
    "Programming Techniques: Regular expression search algorithm")."""
    sim = title_similarity(anchor_title, found_title)
    a, b = title_key(anchor_title), title_key(found_title)
    short, long_ = sorted((a, b), key=len)
    contained = short and f" {short} " in f" {long_} "
    if contained and len(short.split()) >= 3 and len(short) >= len(long_) / 2:
        return 1.0
    return sim


def _compare(anchor: AnchorEntry, found: Found, what: str, status: AnchorStatus) -> None:
    sim = title_match(anchor.title, found.title)
    if sim < TITLE_MIN:
        status.problems.append(
            f"{what}: {found.source} has a different title ({sim:.2f}): {found.title!r}"
        )
        return
    status.verified.append(f"{what} ({found.source}, {sim:.2f})")
    if found.year is not None and abs(found.year - anchor.year) > YEAR_SLACK:
        # The title matches the identifier's record, so the identifier names the work; sources
        # disagree on years (LNCS volumes printed two years later, online-first dates).
        status.notes.append(f"{what}: {found.source} gives year {found.year}, not {anchor.year}")


def verify(
    anchors: Sequence[AnchorEntry],
    corpus: Corpus,
    *,
    doi_lookup: Callable[[str], Found | None | str],
    dump_records: Mapping[str, Found] | None = None,
) -> list[AnchorStatus]:
    """Check each anchor's identifiers. ``dump_records`` holds the DBLP keys found in the dump;
    None means the dump was not read, so keys outside the warehouse stay unchecked."""
    out = []
    for anchor in anchors:
        status = AnchorStatus(anchor, work_id=corpus.work_of(anchor))
        if anchor.doi:
            found = doi_lookup(anchor.doi)
            if found == "uncached":
                status.problems.append("doi: not in the cache (run without --offline)")
            elif found is None:
                status.problems.append(f"doi {anchor.doi}: OpenAlex does not know it")
            else:
                assert isinstance(found, Found)
                _compare(anchor, found, "doi", status)
        if anchor.dblp:
            record = corpus.dblp_records.get(anchor.dblp)
            if record is None and dump_records is not None:
                record = dump_records.get(anchor.dblp)
            if record is not None:
                _compare(anchor, record, "dblp", status)
            elif dump_records is None:
                status.problems.append("dblp: key outside the warehouse and the dump was not read")
            else:
                status.problems.append(f"dblp {anchor.dblp}: not in the DBLP dump")
        if anchor.kind == "pilot" and status.work_id is None:
            status.problems.append("kind is pilot but the work is not in the corpus")
        out.append(status)
    return out


def needs_dump(anchors: Iterable[AnchorEntry], corpus: Corpus) -> list[str]:
    """DBLP keys that only the dump can confirm."""
    return sorted({a.dblp for a in anchors if a.dblp and a.dblp not in corpus.dblp_records})


def candidates(anchor: AnchorEntry, found: Iterable[Found]) -> list[tuple[float, Found]]:
    """Plausible records for an anchor without identifiers, best first."""
    scored = []
    for f in found:
        if f.year is not None and abs(f.year - anchor.year) > YEAR_SLACK:
            continue
        sim = title_match(anchor.title, f.title)
        if sim >= TITLE_MIN:
            scored.append((sim, f))
    return sorted(scored, key=lambda p: (-p[0], p[1].dblp or "", p[1].doi or ""))
