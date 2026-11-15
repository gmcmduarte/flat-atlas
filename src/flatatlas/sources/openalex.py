"""OpenAlex enrichment of the DBLP papers (P1-02).

DBLP defines which papers belong to a venue (PLAN §8.4); OpenAlex is joined to them, never the
other way round.

* **Harvest** (network, through ``SourceClient``): works by DOI, 100 per call (the maximum, checked
  on 2026-11-15, ``docs/notes/sources.md``), and for papers without a DOI a capped title search
  (``filter=title.search``, USD 0.001 a call). The answers are cached by the client; nothing else
  is stored by the harvest except the cursor in ``ops_harvest_state``.
* **Parse** (offline): reads the cached answers back, joins them to the DBLP papers and writes the
  ``stg_openalex_*`` tables. Which DOIs were *asked* is read from the cached request URLs, so a
  ``--limit`` run followed by a full run needs no bookkeeping: a DOI that was asked and not
  returned is "fetched, not found"; a DOI never asked is "not fetched".
* **Abstracts** are rebuilt from the inverted index and go to ``local_abstract`` only. They are
  local-use data and never leave the warehouse (CLAUDE.md rule 2).
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import duckdb
import pyarrow as pa
from rapidfuzz import fuzz

from flatatlas.db import replace_table
from flatatlas.harvest import Page, paged
from flatatlas.http import SourceClient
from flatatlas.settings import Paths
from flatatlas.sources.dblp import normalize_title

log = logging.getLogger(__name__)

SOURCE = "openalex"
PARSER_VERSION = "openalex-parse/1"
DOI_PREFIX = "https://doi.org/"
TITLE_MATCH_MIN = 0.95  # normalised title similarity needed to accept a title-search hit
TITLE_YEAR_SLACK = 1  # DBLP edition year and OpenAlex publication year may differ by this much
DEFAULT_MAX_TITLE_SEARCHES = 400
TABLES = (
    "stg_openalex_lookup",
    "stg_openalex_work",
    "stg_openalex_authorship",
    "stg_openalex_reference",
    "stg_openalex_topic",
    "stg_reference_candidates",
)

# Only what the pipeline uses (PLAN §5.2). Changing this list changes the request URLs, which is
# also how ``parse`` tells current answers from older probes in the cache.
SELECT = ",".join(
    [
        "id",
        "doi",
        "title",
        "publication_year",
        "publication_date",
        "type",
        "language",
        "authorships",
        "referenced_works",
        "referenced_works_count",
        "cited_by_count",
        "counts_by_year",
        "topics",
        "keywords",
        "abstract_inverted_index",
        "open_access",
        "primary_location",
        "biblio",
        "updated_date",
    ]
)


# -- papers to look up ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PaperRef:
    """The few DBLP fields a lookup needs."""

    dblp_key: str
    venue_id: str
    year: int | None
    title: str
    title_norm: str
    doi: str | None


def load_papers(
    con: duckdb.DuckDBPyConnection,
    *,
    venue_ids: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[PaperRef]:
    """DBLP papers (front matter left out) in a fixed order.

    With ``limit`` the order is a hash of the key, so a small run is a mixed sample of venues,
    decades and papers without DOI; without it the order is the key.
    """
    where = "NOT is_front_matter"
    args: list[Any] = []
    if venue_ids:
        where += f" AND venue_id IN ({', '.join('?' * len(venue_ids))})"
        args += list(venue_ids)
    order = "hash(dblp_key || 'p1-02-sample'), dblp_key" if limit else "dblp_key"
    sql = (
        "SELECT dblp_key, venue_id, year, title, title_norm, doi FROM stg_dblp_paper "
        f"WHERE {where} ORDER BY {order}"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [PaperRef(*row) for row in con.execute(sql, args).fetchall()]


# -- request building ----------------------------------------------------------------------------

_UNSAFE_IN_FILTER = re.compile(r"[,|]")
_NOT_QUERY_CHARS = re.compile(r"[^\w\s-]+")


def doi_is_filterable(doi: str) -> bool:
    """A DOI with a comma or a pipe would break the filter syntax; those go to title search."""
    return _UNSAFE_IN_FILTER.search(doi) is None


def doi_batches(dois: Iterable[str], size: int) -> list[list[str]]:
    """Unique, lower-case, sorted DOIs in chunks of ``size`` (stable, so re-runs hit the cache)."""
    unique = sorted({d.lower() for d in dois if d and doi_is_filterable(d)})
    return [unique[i : i + size] for i in range(0, len(unique), size)]


def batch_params(batch: Sequence[str]) -> dict[str, Any]:
    return {
        "filter": "doi:" + "|".join(DOI_PREFIX + d for d in batch),
        "per_page": 200,
        "select": SELECT,
    }


def title_query(title: str) -> str:
    """Words only: punctuation can be filter or search syntax."""
    return re.sub(r"\s+", " ", _NOT_QUERY_CHARS.sub(" ", title)).strip()


def title_params(paper: PaperRef) -> dict[str, Any] | None:
    query = title_query(paper.title)
    if not query or paper.year is None:
        return None
    years = "|".join(str(paper.year + d) for d in range(-TITLE_YEAR_SLACK, TITLE_YEAR_SLACK + 1))
    return {
        "filter": f"title.search:{query},publication_year:{years}",
        "per_page": 5,
        "select": SELECT,
    }


def title_search_plan(papers: Sequence[PaperRef], cap: int) -> list[PaperRef]:
    """The papers that get a title search: no usable DOI, the first ``cap`` in key order."""
    candidates = [p for p in papers if (p.doi is None or not doi_is_filterable(p.doi))]
    candidates = sorted(candidates, key=lambda p: p.dblp_key)
    return [p for p in candidates if title_params(p) is not None][: max(cap, 0)]


# -- harvest -------------------------------------------------------------------------------------


@dataclass
class HarvestStats:
    batches: int = 0
    batches_from_cache: int = 0
    works_returned: int = 0
    searches: int = 0
    searches_from_cache: int = 0
    papers_without_search: int = 0
    notes: list[str] = field(default_factory=list)

    def as_counts(self) -> dict[str, int]:
        return {
            "doi_batches": self.batches,
            "doi_batches_from_cache": self.batches_from_cache,
            "works_returned": self.works_returned,
            "title_searches": self.searches,
            "title_searches_from_cache": self.searches_from_cache,
            "papers_not_searched": self.papers_without_search,
        }


def _job_key(prefix: str, items: Iterable[str]) -> str:
    digest = hashlib.sha1("\n".join(items).encode()).hexdigest()[:10]  # noqa: S324 - not security
    return f"{prefix}:{digest}"


def harvest(
    con: duckdb.DuckDBPyConnection,
    client: SourceClient,
    papers: Sequence[PaperRef],
    *,
    max_title_searches: int = DEFAULT_MAX_TITLE_SEARCHES,
    restart: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> HarvestStats:
    """Fetch the DOI batches, then the capped title searches. Resumable and idempotent.

    Raises ``BudgetExhausted`` when the day's budget is used up; the cursor is saved, so the same
    command continues after midnight UTC.
    """
    stats = HarvestStats()
    say = on_progress or (lambda _msg: None)

    batches = doi_batches((p.doi for p in papers if p.doi), client.cfg.batch_size)
    if batches:
        job = _job_key("works-by-doi", [d for b in batches for d in b])

        def fetch_batch(cursor: str | None) -> Page:
            index = int(cursor or 0)
            resp = client.get("/works", batch_params(batches[index]))
            stats.batches += 1
            stats.batches_from_cache += resp.from_cache
            works = resp.data["results"]
            stats.works_returned += len(works)
            say(f"doi batch {index + 1}/{len(batches)}: {len(works)} works")
            nxt = str(index + 1) if index + 1 < len(batches) else None
            return Page(items=works, next_cursor=nxt)

        for _page in paged(con, SOURCE, job, fetch_batch, restart=restart):
            pass

    plan = title_search_plan(papers, max_title_searches)
    stats.papers_without_search = sum(
        1 for p in papers if p.doi is None or not doi_is_filterable(p.doi)
    ) - len(plan)
    if plan:
        job = _job_key("title-search", [p.dblp_key for p in plan])

        def fetch_search(cursor: str | None) -> Page:
            index = int(cursor or 0)
            params = title_params(plan[index])
            assert params is not None  # the plan only holds searchable papers
            resp = client.get("/works", params, cost="search")
            stats.searches += 1
            stats.searches_from_cache += resp.from_cache
            if (index + 1) % 25 == 0 or index + 1 == len(plan):
                say(f"title search {index + 1}/{len(plan)}")
            nxt = str(index + 1) if index + 1 < len(plan) else None
            return Page(items=resp.data["results"], next_cursor=nxt)

        for _page in paged(con, SOURCE, job, fetch_search, restart=restart):
            pass
    return stats


# -- parsing one work ----------------------------------------------------------------------------


def short_id(url: str | None) -> str | None:
    """``https://openalex.org/W123`` -> ``W123``."""
    return url.rsplit("/", 1)[-1] if url else None


_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", re.IGNORECASE)


def normalize_doi(doi: str | None) -> str | None:
    """Bare, lower-case DOI from any of the usual spellings (URL, ``doi:``, bare)."""
    if not doi:
        return None
    return _DOI_PREFIX_RE.sub("", doi.strip()).lower() or None


def reconstruct_abstract(index: dict[str, list[int]] | None) -> str | None:
    """Rebuild the text from OpenAlex's ``abstract_inverted_index`` (word -> positions)."""
    if not index:
        return None
    slots: dict[int, str] = {}
    for word, positions in index.items():
        for pos in positions or []:
            slots[pos] = word
    if not slots:
        return None
    text = " ".join(slots[pos] for pos in sorted(slots)).strip()
    return text or None


def _strip(url: str | None, prefix: str) -> str | None:
    if not url:
        return None
    return url[len(prefix) :] if url.startswith(prefix) else url


@dataclass
class ParsedWork:
    work: dict[str, Any]
    authorships: list[dict[str, Any]]
    references: list[dict[str, Any]]
    topics: list[dict[str, Any]]
    abstract: str | None


def parse_work(raw: dict[str, Any], fetched_at: str | None = None) -> ParsedWork:
    """One OpenAlex work -> rows. Tolerates every field being missing or null."""
    wid = short_id(raw.get("id"))
    abstract = reconstruct_abstract(raw.get("abstract_inverted_index"))
    oa = raw.get("open_access") or {}
    loc = raw.get("primary_location") or {}
    src = loc.get("source") or {}
    biblio = raw.get("biblio") or {}
    refs = [short_id(r) for r in raw.get("referenced_works") or []]
    refs = [r for r in refs if r]

    authorships: list[dict[str, Any]] = []
    n_with_inst = n_with_country = 0
    raw_authors = raw.get("authorships") or []
    for position, auth in enumerate(raw_authors):
        author = auth.get("author") or {}
        institutions = auth.get("institutions") or []
        raw_by_inst: dict[str, list[str]] = {}
        for aff in auth.get("affiliations") or []:
            for inst_id in aff.get("institution_ids") or []:
                raw_by_inst.setdefault(short_id(inst_id) or "", []).append(
                    aff.get("raw_affiliation_string") or ""
                )
        raw_strings = [s for s in auth.get("raw_affiliation_strings") or [] if s]
        base = {
            "openalex_id": wid,
            "position": position,
            "author_position": auth.get("author_position"),
            "author_id": short_id(author.get("id")),
            "author_name": author.get("display_name"),
            "orcid": _strip(author.get("orcid"), "https://orcid.org/"),
            "raw_author_name": auth.get("raw_author_name"),
            "is_corresponding": auth.get("is_corresponding"),
        }
        if institutions:
            n_with_inst += 1
            n_with_country += any(i.get("country_code") for i in institutions)
            for inst in institutions:
                iid = short_id(inst.get("id"))
                authorships.append(
                    {
                        **base,
                        "institution_id": iid,
                        "institution_name": inst.get("display_name"),
                        "ror": _strip(inst.get("ror"), "https://ror.org/"),
                        "country_code": inst.get("country_code"),
                        "institution_type": inst.get("type"),
                        "raw_affiliation": " | ".join(
                            s for s in raw_by_inst.get(iid or "", raw_strings) if s
                        )
                        or None,
                    }
                )
        else:
            authorships.append(
                {
                    **base,
                    "institution_id": None,
                    "institution_name": None,
                    "ror": None,
                    "country_code": None,
                    "institution_type": None,
                    "raw_affiliation": " | ".join(raw_strings) or None,
                }
            )

    topics: list[dict[str, Any]] = []
    for rank, topic in enumerate(raw.get("topics") or []):
        topics.append(
            {
                "openalex_id": wid,
                "kind": "topic",
                "rank": rank,
                "topic_id": short_id(topic.get("id")),
                "name": topic.get("display_name"),
                "score": topic.get("score"),
                "subfield": (topic.get("subfield") or {}).get("display_name"),
                "field": (topic.get("field") or {}).get("display_name"),
                "domain": (topic.get("domain") or {}).get("display_name"),
            }
        )
    for rank, kw in enumerate(raw.get("keywords") or []):
        topics.append(
            {
                "openalex_id": wid,
                "kind": "keyword",
                "rank": rank,
                "topic_id": short_id(kw.get("id")),
                "name": kw.get("display_name"),
                "score": kw.get("score"),
                "subfield": None,
                "field": None,
                "domain": None,
            }
        )

    work = {
        "openalex_id": wid,
        "doi": normalize_doi(raw.get("doi")),
        "title": raw.get("title"),
        "publication_year": raw.get("publication_year"),
        "publication_date": raw.get("publication_date"),
        "type": raw.get("type"),
        "language": raw.get("language"),
        "cited_by_count": raw.get("cited_by_count"),
        "referenced_works_count": raw.get("referenced_works_count"),
        "n_references_listed": len(refs),
        "counts_by_year": [
            {"year": c.get("year"), "cited_by_count": c.get("cited_by_count")}
            for c in raw.get("counts_by_year") or []
            if c.get("year") is not None
        ],
        "has_abstract": abstract is not None,
        "abstract_chars": len(abstract) if abstract else None,
        "is_oa": oa.get("is_oa"),
        "oa_status": oa.get("oa_status"),
        "oa_url": oa.get("oa_url"),
        "landing_page_url": loc.get("landing_page_url"),
        "source_id": short_id(src.get("id")),
        "source_name": src.get("display_name"),
        "source_issn_l": src.get("issn_l"),
        "volume": biblio.get("volume"),
        "issue": biblio.get("issue"),
        "first_page": biblio.get("first_page"),
        "last_page": biblio.get("last_page"),
        "n_authors": len(raw_authors),
        "n_authors_with_institution": n_with_inst,
        "n_authors_with_country": n_with_country,
        "updated_date": raw.get("updated_date"),
        "fetched_at": fetched_at,
        "parser_version": PARSER_VERSION,
    }
    references = [
        {"citing_openalex_id": wid, "cited_openalex_id": ref, "position": i}
        for i, ref in enumerate(refs)
    ]
    return ParsedWork(work, authorships, references, topics, abstract)


# -- joining answers to papers -------------------------------------------------------------------


@dataclass
class CachedAnswers:
    """Everything the cache holds for the current ``SELECT``."""

    asked_dois: set[str] = field(default_factory=set)
    works_by_doi: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)


def _is_current(query: dict[str, list[str]]) -> bool:
    return query.get("select") == [SELECT]


def read_cached_answers(client: SourceClient) -> CachedAnswers:
    """Scan the cache for DOI-batch answers; newest answer wins per DOI."""
    answers = CachedAnswers()
    for resp in client.iter_cached("/works"):
        if resp.status != 200 or not isinstance(resp.data, dict):
            continue
        query = parse_qs(urlparse(resp.url).query)
        if not _is_current(query):
            continue
        flt = (query.get("filter") or [""])[0]
        if not flt.startswith("doi:"):
            continue
        for part in flt[len("doi:") :].split("|"):
            doi = normalize_doi(part)
            if doi:
                answers.asked_dois.add(doi)
        stamp = resp.fetched_at.isoformat()
        for work in resp.data.get("results") or []:
            doi = normalize_doi(work.get("doi"))
            if doi and (doi not in answers.works_by_doi or answers.works_by_doi[doi][0] < stamp):
                answers.works_by_doi[doi] = (stamp, work)
    return answers


def best_title_match(
    paper: PaperRef, candidates: Sequence[dict[str, Any]]
) -> tuple[dict[str, Any] | None, float]:
    """The candidate with the most similar normalised title, if it is similar enough and close in
    year. Returns ``(work, score)``; the score is of the best candidate even when it is rejected."""
    best: dict[str, Any] | None = None
    best_score = 0.0
    for cand in candidates:
        year = cand.get("publication_year")
        if (
            paper.year is not None
            and year is not None
            and abs(year - paper.year) > TITLE_YEAR_SLACK
        ):
            continue
        score = fuzz.ratio(paper.title_norm, normalize_title(cand.get("title") or "")) / 100
        if score > best_score:
            best, best_score = cand, score
    if best is not None and best_score >= TITLE_MATCH_MIN:
        return best, best_score
    return None, best_score


@dataclass
class ParsedOpenAlex:
    lookup: list[dict[str, Any]] = field(default_factory=list)
    works: list[dict[str, Any]] = field(default_factory=list)
    authorships: list[dict[str, Any]] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    topics: list[dict[str, Any]] = field(default_factory=list)
    abstracts: list[dict[str, Any]] = field(default_factory=list)
    reference_candidates: list[dict[str, Any]] = field(default_factory=list)
    stats: Counter = field(default_factory=Counter)


def parse_openalex(client: SourceClient, papers: Sequence[PaperRef]) -> ParsedOpenAlex:
    """Join the cached answers to ``papers``. No network."""
    answers = read_cached_answers(client)
    out = ParsedOpenAlex()
    seen_works: dict[str, ParsedWork] = {}
    matched_for: list[tuple[PaperRef, str, str]] = []  # paper, openalex_id, doi-or-None

    def take(raw: dict[str, Any], fetched_at: str) -> str | None:
        parsed = parse_work(raw, fetched_at)
        wid = parsed.work["openalex_id"]
        if wid and wid not in seen_works:
            seen_works[wid] = parsed
        return wid

    for paper in papers:
        doi = normalize_doi(paper.doi)
        row: dict[str, Any] = {
            "dblp_key": paper.dblp_key,
            "venue_id": paper.venue_id,
            "lookup_kind": "none",
            "fetched": False,
            "openalex_id": None,
            "match_method": None,
            "match_confidence": None,
            "n_candidates": None,
            "parser_version": PARSER_VERSION,
        }
        if doi and doi_is_filterable(doi):
            row["lookup_kind"] = "doi"
            row["fetched"] = doi in answers.asked_dois
            hit = answers.works_by_doi.get(doi)
            if hit:
                wid = take(hit[1], hit[0])
                row.update(openalex_id=wid, match_method="doi-exact", match_confidence=1.0)
        else:
            params = title_params(paper)
            resp = client.cached("/works", params) if params else None
            if params is not None:
                row["lookup_kind"] = "title"
            if resp is not None and resp.status == 200 and isinstance(resp.data, dict):
                row["fetched"] = True
                cands = resp.data.get("results") or []
                row["n_candidates"] = len(cands)
                work, score = best_title_match(paper, cands)
                if work is not None:
                    wid = take(work, resp.fetched_at.isoformat())
                    row.update(
                        openalex_id=wid,
                        match_method=f"title-search>={TITLE_MATCH_MIN}",
                        match_confidence=round(score, 4),
                    )
                else:
                    row["match_confidence"] = round(score, 4) if cands else None
        if row["openalex_id"]:
            matched_for.append((paper, row["openalex_id"], doi or ""))
        out.lookup.append(row)
        out.stats[f"lookup_{row['lookup_kind']}"] += 1
        out.stats["fetched"] += bool(row["fetched"])
        out.stats["matched"] += bool(row["openalex_id"])

    for parsed in seen_works.values():
        out.works.append(parsed.work)
        out.authorships.extend(parsed.authorships)
        out.references.extend(parsed.references)
        out.topics.extend(parsed.topics)
    for paper, wid, doi in matched_for:
        text = seen_works[wid].abstract
        if text:
            out.abstracts.append(
                {
                    "dblp_key": paper.dblp_key,
                    "openalex_id": wid,
                    "doi": doi or None,
                    "source": SOURCE,
                    "text": text,
                    "n_chars": len(text),
                }
            )
    out.reference_candidates = reference_candidates(out.references, set(seen_works))
    out.stats["works"] = len(out.works)
    out.stats["abstracts"] = len(out.abstracts)
    out.stats["references"] = len(out.references)
    out.stats["reference_candidates"] = len(out.reference_candidates)
    return out


def reference_candidates(
    references: Iterable[dict[str, Any]], pilot_ids: set[str]
) -> list[dict[str, Any]]:
    """Works the pilot papers cite that are not pilot papers, with how many pilot papers cite
    each (the raw material for stubs, PLAN §4.2 ``core_stub``)."""
    counts: Counter[str] = Counter()
    for ref in references:
        cited = ref["cited_openalex_id"]
        if cited not in pilot_ids:
            counts[cited] += 1
    return [
        {"openalex_id": oid, "n_citing_pilot_works": n}
        for oid, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def sample_rows(parsed: ParsedOpenAlex, n: int = 10, seed: str = "p1-02") -> list[dict[str, Any]]:
    """``n`` matched papers, chosen by a hash of their key, with the fields worth eyeballing."""
    by_id = {w["openalex_id"]: w for w in parsed.works}
    authors: dict[str, list[dict[str, Any]]] = {}
    for a in parsed.authorships:
        authors.setdefault(a["openalex_id"], []).append(a)
    matched = [r for r in parsed.lookup if r["openalex_id"]]
    matched.sort(key=lambda r: hashlib.sha1(f"{r['dblp_key']}{seed}".encode()).hexdigest())
    rows = []
    for r in matched[:n]:
        w = by_id[r["openalex_id"]]
        rows.append(
            {
                "dblp_key": r["dblp_key"],
                "openalex_id": w["openalex_id"],
                "match": f"{r['match_method']} ({r['match_confidence']})",
                "title": w["title"],
                "year": w["publication_year"],
                "cited_by": w["cited_by_count"],
                "references": w["n_references_listed"],
                "abstract_chars": w["abstract_chars"],
                "authors": [
                    f"{a['author_name']} ({a['institution_name'] or '-'}, "
                    f"{a['country_code'] or '-'})"
                    for a in authors.get(w["openalex_id"], [])
                ][:4],
                "top_topic": next(
                    (t["name"] for t in parsed.topics if t["openalex_id"] == w["openalex_id"]),
                    None,
                ),
            }
        )
    return rows


# -- storage -------------------------------------------------------------------------------------

_S = pa.string()
_SCHEMAS: dict[str, pa.Schema] = {
    "stg_openalex_lookup": pa.schema(
        [
            ("dblp_key", _S),
            ("venue_id", _S),
            ("lookup_kind", _S),  # doi | title | none (no DOI and no usable title)
            ("fetched", pa.bool_()),
            ("openalex_id", _S),
            ("match_method", _S),
            ("match_confidence", pa.float32()),
            ("n_candidates", pa.int16()),
            ("parser_version", _S),
        ]
    ),
    "stg_openalex_work": pa.schema(
        [
            ("openalex_id", _S),
            ("doi", _S),
            ("title", _S),
            ("publication_year", pa.int16()),
            ("publication_date", _S),
            ("type", _S),
            ("language", _S),
            ("cited_by_count", pa.int32()),
            ("referenced_works_count", pa.int32()),
            ("n_references_listed", pa.int32()),
            (
                "counts_by_year",
                pa.list_(pa.struct([("year", pa.int16()), ("cited_by_count", pa.int32())])),
            ),
            ("has_abstract", pa.bool_()),
            ("abstract_chars", pa.int32()),
            ("is_oa", pa.bool_()),
            ("oa_status", _S),
            ("oa_url", _S),
            ("landing_page_url", _S),
            ("source_id", _S),
            ("source_name", _S),
            ("source_issn_l", _S),
            ("volume", _S),
            ("issue", _S),
            ("first_page", _S),
            ("last_page", _S),
            ("n_authors", pa.int16()),
            ("n_authors_with_institution", pa.int16()),
            ("n_authors_with_country", pa.int16()),
            ("updated_date", _S),
            ("fetched_at", _S),
            ("parser_version", _S),
        ]
    ),
    "stg_openalex_authorship": pa.schema(
        [
            ("openalex_id", _S),
            ("position", pa.int16()),
            ("author_position", _S),
            ("author_id", _S),
            ("author_name", _S),
            ("orcid", _S),
            ("raw_author_name", _S),
            ("is_corresponding", pa.bool_()),
            ("institution_id", _S),
            ("institution_name", _S),
            ("ror", _S),
            ("country_code", _S),
            ("institution_type", _S),
            ("raw_affiliation", _S),
        ]
    ),
    "stg_openalex_reference": pa.schema(
        [
            ("citing_openalex_id", _S),
            ("cited_openalex_id", _S),
            ("position", pa.int32()),
        ]
    ),
    "stg_openalex_topic": pa.schema(
        [
            ("openalex_id", _S),
            ("kind", _S),  # topic | keyword
            ("rank", pa.int16()),
            ("topic_id", _S),
            ("name", _S),
            ("score", pa.float32()),
            ("subfield", _S),
            ("field", _S),
            ("domain", _S),
        ]
    ),
    "stg_reference_candidates": pa.schema(
        [("openalex_id", _S), ("n_citing_pilot_works", pa.int32())]
    ),
}

LOCAL_ABSTRACT_SCHEMA = pa.schema(
    [
        ("dblp_key", _S),
        ("openalex_id", _S),
        ("doi", _S),
        ("source", _S),
        ("text", _S),
        ("n_chars", pa.int32()),
    ]
)


def to_arrow(parsed: ParsedOpenAlex) -> dict[str, pa.Table]:
    rows = {
        "stg_openalex_lookup": parsed.lookup,
        "stg_openalex_work": parsed.works,
        "stg_openalex_authorship": parsed.authorships,
        "stg_openalex_reference": parsed.references,
        "stg_openalex_topic": parsed.topics,
        "stg_reference_candidates": parsed.reference_candidates,
    }
    return {
        name: pa.Table.from_pylist(rows[name], schema=schema) for name, schema in _SCHEMAS.items()
    }


def write_local_abstracts(
    con: duckdb.DuckDBPyConnection, paths: Paths, source: str, rows: list[dict[str, Any]]
) -> None:
    """Replace the ``source`` rows of ``local_abstract`` and keep the other sources' rows.

    Local-only table (PLAN §4.2): it lives in the warehouse and in ``warehouse/local/`` and is
    never exported. Keyed by ``dblp_key`` until the resolve stage (P1-04) mints work IDs.
    """
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    kept: list[dict[str, Any]] = []
    if "local_abstract" in tables:
        cur = con.execute(
            "SELECT dblp_key, openalex_id, doi, source, text, n_chars FROM local_abstract "
            "WHERE source <> ?",
            [source],
        )
        names = [d[0] for d in cur.description]
        kept = [dict(zip(names, row, strict=True)) for row in cur.fetchall()]
    table = pa.Table.from_pylist(kept + rows, schema=LOCAL_ABSTRACT_SCHEMA)
    replace_table(
        con, "local_abstract", table, paths.warehouse / "local" / "local_abstract.parquet"
    )


def write_tables(con: duckdb.DuckDBPyConnection, paths: Paths, parsed: ParsedOpenAlex) -> None:
    for name, table in to_arrow(parsed).items():
        replace_table(con, name, table, paths.warehouse / "staging" / f"{name}.parquet")
    write_local_abstracts(con, paths, SOURCE, parsed.abstracts)
