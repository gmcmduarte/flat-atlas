"""Semantic Scholar enrichment of the DBLP papers (P1-03).

DBLP defines which papers exist; Semantic Scholar (S2) is joined to them, never the other way.

* **Harvest** (network, through ``SourceClient``):
  1. ``POST /paper/batch`` with ``DOI:<doi>`` IDs, 500 per call (the maximum; 501 gives HTTP 400).
     S2 does **not** accept ``DBLP:<key>`` IDs: it answers ``null`` even for papers it holds
     (checked 2026-11-16, ``docs/notes/sources.md``).
  2. ``GET /paper/search/match`` (best title match, one call each) for every paper that step 1 did
     not return: those without a DOI and those S2 does not know by DOI. Capped, resumable.
  The answers are cached by the client; nothing else is stored except the cursor in
  ``ops_harvest_state``.
* **Parse** (offline): reads the cached answers back. Which DOIs were *asked* comes from the POST
  body the cache keeps (``Response.request_body``) and the answers are aligned by position, so a
  ``--limit`` run followed by a full run needs no bookkeeping: asked and returned ``null`` is
  "not found", never asked is "not fetched".
* **Abstracts** go to ``local_abstract`` (source ``s2``) and vectors to ``local_embedding`` (source
  ``s2``); both are local-use data and never leave the warehouse (CLAUDE.md rule 2). The TLDR text
  sits in ``stg_s2_paper`` and, like every ``stg_*`` table, is not exported.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import duckdb
import pyarrow as pa
from rapidfuzz import fuzz

from flatatlas.db import replace_table
from flatatlas.embed import store
from flatatlas.harvest import Page, paged
from flatatlas.http import SourceClient
from flatatlas.settings import Paths
from flatatlas.sources.dblp import normalize_title
from flatatlas.sources.openalex import (
    TITLE_MATCH_MIN,
    TITLE_YEAR_SLACK,
    PaperRef,
    normalize_doi,
    write_local_abstracts,
)

log = logging.getLogger(__name__)

SOURCE = "semanticscholar"
ABSTRACT_SOURCE = "s2"  # value of local_abstract.source and local_embedding.source
PARSER_VERSION = "s2-parse/1"
EMBEDDING_MODEL = "specter_v2"
DEFAULT_MAX_TITLE_MATCHES = 1000
TABLES = ("stg_s2_lookup", "stg_s2_paper", "stg_s2_reference")

# ``references.isInfluential`` is not accepted here (HTTP 400, checked 2026-11-16): the per-edge
# "influential" flag exists only on ``/paper/{id}/references`` (one call per paper) and in the
# datasets, so it is not harvested in P1-03; the per-paper count is.
# ``paperId`` and a few more come back whatever is asked. Changing this list changes the request
# URLs, which is also how ``parse`` tells current answers from older probes in the cache.
FIELDS = ",".join(
    [
        "corpusId",
        "externalIds",
        "title",
        "year",
        "abstract",
        "tldr",
        "citationCount",
        "influentialCitationCount",
        "references.corpusId",
        "embedding.specter_v2",
    ]
)
BATCH_PATH = "/paper/batch"
MATCH_PATH = "/paper/search/match"


# -- request building ----------------------------------------------------------------------------


def doi_batches(dois: Iterable[str], size: int) -> list[list[str]]:
    """Unique, lower-case, sorted DOIs in chunks of ``size`` (stable, so re-runs hit the cache)."""
    unique = sorted({d.lower() for d in dois if d})
    return [unique[i : i + size] for i in range(0, len(unique), size)]


def batch_body(batch: Sequence[str]) -> dict[str, Any]:
    return {"ids": [f"DOI:{d}" for d in batch]}


def batch_params() -> dict[str, Any]:
    return {"fields": FIELDS}


def match_params(paper: PaperRef) -> dict[str, Any] | None:
    title = " ".join(paper.title.split())
    return {"query": title, "fields": FIELDS} if title else None


# -- reading the cache ---------------------------------------------------------------------------


@dataclass
class CachedAnswers:
    """What the cache holds for the current ``FIELDS``: DOI batches, newest answer per DOI."""

    # doi -> (fetched_at, item or None). None means: asked, S2 answered null.
    by_doi: dict[str, tuple[str, dict[str, Any] | None]] = field(default_factory=dict)

    @property
    def asked(self) -> set[str]:
        return set(self.by_doi)

    def item(self, doi: str) -> dict[str, Any] | None:
        entry = self.by_doi.get(doi)
        return entry[1] if entry else None


def read_cached_answers(client: SourceClient) -> CachedAnswers:
    """Scan the cache for DOI-batch answers. Answer ``i`` belongs to ID ``i`` of the request."""
    answers = CachedAnswers()
    for resp in client.iter_cached(BATCH_PATH):
        if resp.status != 200 or not isinstance(resp.data, list):
            continue
        if parse_qs(urlparse(resp.url).query).get("fields") != [FIELDS]:
            continue  # a probe or an older field list
        ids = (resp.request_body or {}).get("ids") or []
        stamp = resp.fetched_at.isoformat()
        for i, ident in enumerate(ids):
            if not ident.startswith("DOI:"):
                continue
            doi = normalize_doi(ident[len("DOI:") :])
            item = resp.data[i] if i < len(resp.data) else None
            old = answers.by_doi.get(doi) if doi else None
            if doi and (old is None or old[0] <= stamp):
                answers.by_doi[doi] = (stamp, item if isinstance(item, dict) else None)
    return answers


def title_match_plan(
    papers: Sequence[PaperRef], answers: CachedAnswers, cap: int
) -> tuple[list[PaperRef], int]:
    """Papers that get a title match: no DOI, or S2 did not return their DOI. Key order, capped.

    Returns ``(plan, n_left_out_by_the_cap)``.
    """
    wanted = [
        p
        for p in sorted(papers, key=lambda p: p.dblp_key)
        if (p.doi is None or answers.item(p.doi.lower()) is None) and match_params(p) is not None
    ]
    cap = max(cap, 0)
    return wanted[:cap], max(len(wanted) - cap, 0)


# -- harvest -------------------------------------------------------------------------------------


@dataclass
class HarvestStats:
    batches: int = 0
    batches_from_cache: int = 0
    items_returned: int = 0
    matches: int = 0
    matches_from_cache: int = 0
    papers_not_matched_by_cap: int = 0

    def as_counts(self) -> dict[str, int]:
        return {
            "doi_batches": self.batches,
            "doi_batches_from_cache": self.batches_from_cache,
            "items_returned": self.items_returned,
            "title_matches": self.matches,
            "title_matches_from_cache": self.matches_from_cache,
            "papers_not_title_matched": self.papers_not_matched_by_cap,
        }


def _job_key(prefix: str, items: Iterable[str]) -> str:
    digest = hashlib.sha1("\n".join(items).encode()).hexdigest()[:10]  # noqa: S324 - not security
    return f"{prefix}:{digest}"


def harvest(
    con: duckdb.DuckDBPyConnection,
    client: SourceClient,
    papers: Sequence[PaperRef],
    *,
    max_title_matches: int = DEFAULT_MAX_TITLE_MATCHES,
    restart: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> HarvestStats:
    """Fetch the DOI batches, then the capped title matches. Resumable and idempotent."""
    stats = HarvestStats()
    say = on_progress or (lambda _msg: None)

    batches = doi_batches((p.doi for p in papers if p.doi), client.cfg.batch_size)
    if batches:
        job = _job_key("batch-by-doi", [d for b in batches for d in b])

        def fetch_batch(cursor: str | None) -> Page:
            index = int(cursor or 0)
            resp = client.post(BATCH_PATH, batch_body(batches[index]), batch_params())
            stats.batches += 1
            stats.batches_from_cache += resp.from_cache
            found = [x for x in resp.data if x]
            stats.items_returned += len(found)
            say(f"doi batch {index + 1}/{len(batches)}: {len(found)}/{len(batches[index])} found")
            nxt = str(index + 1) if index + 1 < len(batches) else None
            return Page(items=found, next_cursor=nxt)

        for _page in paged(con, SOURCE, job, fetch_batch, restart=restart):
            pass

    plan, left_out = title_match_plan(papers, read_cached_answers(client), max_title_matches)
    stats.papers_not_matched_by_cap = left_out
    if plan:
        job = _job_key("title-match", [p.dblp_key for p in plan])

        def fetch_match(cursor: str | None) -> Page:
            index = int(cursor or 0)
            params = match_params(plan[index])
            assert params is not None  # the plan only holds searchable papers
            resp = client.get(MATCH_PATH, params)
            stats.matches += 1
            stats.matches_from_cache += resp.from_cache
            if (index + 1) % 25 == 0 or index + 1 == len(plan):
                say(f"title match {index + 1}/{len(plan)}")
            nxt = str(index + 1) if index + 1 < len(plan) else None
            return Page(items=_candidates(resp.data), next_cursor=nxt)

        for _page in paged(con, SOURCE, job, fetch_match, restart=restart):
            pass
    return stats


def _candidates(data: Any) -> list[dict[str, Any]]:
    """The items of a ``search/match`` answer (None for a cached 404 "not found")."""
    items = data.get("data") if isinstance(data, dict) else None
    return [x for x in items or [] if isinstance(x, dict)]


# -- parsing -------------------------------------------------------------------------------------


@dataclass
class ParsedItem:
    paper: dict[str, Any]
    references: list[dict[str, Any]]
    abstract: str | None
    vector: list[float] | None
    bad_vector: bool = False


def parse_item(item: dict[str, Any], fetched_at: str | None = None) -> ParsedItem | None:
    """One S2 paper answer to a staging row, its references, abstract and vector."""
    corpus_id = item.get("corpusId")
    if corpus_id is None:
        return None
    ext = item.get("externalIds") or {}
    refs_raw = item.get("references")
    references = [
        {
            "citing_corpus_id": int(corpus_id),
            "cited_corpus_id": int(ref["corpusId"]),
        }
        for ref in refs_raw or []
        if isinstance(ref, dict) and ref.get("corpusId") is not None
    ]
    abstract = (item.get("abstract") or "").strip() or None
    emb = item.get("embedding") or {}
    vector = emb.get("vector") if emb.get("model") == EMBEDDING_MODEL else None
    bad_vector = vector is not None and len(vector) != store.DIM
    if bad_vector:
        vector = None
    tldr = item.get("tldr") or {}
    paper = {
        "s2_corpus_id": int(corpus_id),
        "s2_paper_id": item.get("paperId"),
        "title": item.get("title"),
        "year": item.get("year"),
        "doi": normalize_doi(ext.get("DOI")),
        "dblp_key": ext.get("DBLP"),
        "citation_count": item.get("citationCount"),
        "influential_citation_count": item.get("influentialCitationCount"),
        "n_references": None if refs_raw is None else len(refs_raw),
        "tldr": (tldr.get("text") or None) if isinstance(tldr, dict) else None,
        "has_abstract": abstract is not None,
        "has_embedding": vector is not None,
        "fetched_at": fetched_at,
        "parser_version": PARSER_VERSION,
    }
    return ParsedItem(paper, references, abstract, vector, bad_vector)


def best_title_match(
    paper: PaperRef, candidates: Sequence[dict[str, Any]]
) -> tuple[dict[str, Any] | None, float]:
    """The candidate with the most similar normalised title, if similar enough and close in year.

    Returns ``(item, score)``; the score is of the best candidate even when it is rejected.
    """
    best: dict[str, Any] | None = None
    best_score = 0.0
    for cand in candidates:
        year = cand.get("year")
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
class ParsedS2:
    lookup: list[dict[str, Any]] = field(default_factory=list)
    papers: list[dict[str, Any]] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    abstracts: list[dict[str, Any]] = field(default_factory=list)
    embeddings: list[dict[str, Any]] = field(default_factory=list)
    stats: Counter = field(default_factory=Counter)


def parse_s2(client: SourceClient, papers: Sequence[PaperRef]) -> ParsedS2:
    """Join the cached answers to the DBLP papers. Offline."""
    out = ParsedS2()
    answers = read_cached_answers(client)
    seen_corpus: set[int] = set()
    stats = out.stats
    stats["papers"] = len(papers)

    for paper in sorted(papers, key=lambda p: p.dblp_key):
        item: dict[str, Any] | None = None
        method: str | None = None
        score: float | None = None
        fetched_at: str | None = None

        doi = paper.doi.lower() if paper.doi else None
        tried_title = False
        if doi and answers.item(doi) is not None:
            item, method = answers.item(doi), "doi"
            fetched_at = answers.by_doi[doi][0]
            score = fuzz.ratio(paper.title_norm, normalize_title(item.get("title") or "")) / 100
        else:
            params = match_params(paper)
            resp = client.cached(MATCH_PATH, params) if params else None
            if resp is not None:
                tried_title = True
                fetched_at = resp.fetched_at.isoformat()
                item, score = best_title_match(paper, _candidates(resp.data))
                method = "title" if item else None

        # "not found" means every route that applies was tried; a paper S2 returned null for by
        # DOI but that has not been title-matched yet (the cap, or a --limit run) is not fetched.
        exhausted = tried_title or (doi is not None and doi in answers.asked and not paper.title)
        status = "matched" if item else ("not_found" if exhausted else "not_fetched")
        parsed = parse_item(item, fetched_at) if item else None
        if item and parsed is None:  # S2 answered an item without a corpus ID
            status, method = "not_found", None
        stats[status] += 1
        if method:
            stats[f"matched_{method}"] += 1

        row: dict[str, Any] = {
            "dblp_key": paper.dblp_key,
            "status": status,
            "method": method,
            "s2_corpus_id": parsed.paper["s2_corpus_id"] if parsed else None,
            "s2_paper_id": parsed.paper["s2_paper_id"] if parsed else None,
            "title_similarity": round(score, 4) if score is not None else None,
            "s2_dblp_key": parsed.paper["dblp_key"] if parsed else None,
            "fetched_at": fetched_at,
            "parser_version": PARSER_VERSION,
        }
        out.lookup.append(row)
        if parsed is None:
            continue
        if row["s2_dblp_key"] and row["s2_dblp_key"] != paper.dblp_key:
            stats["s2_has_other_dblp_key"] += 1  # e.g. the journal version of the same title

        corpus_id = parsed.paper["s2_corpus_id"]
        if corpus_id not in seen_corpus:
            seen_corpus.add(corpus_id)
            out.papers.append(parsed.paper)
            out.references.extend(parsed.references)
            stats["references"] += len(parsed.references)
        if parsed.abstract:
            out.abstracts.append(
                {
                    "dblp_key": paper.dblp_key,
                    "openalex_id": None,
                    "doi": paper.doi,
                    "source": ABSTRACT_SOURCE,
                    "text": parsed.abstract,
                    "n_chars": len(parsed.abstract),
                }
            )
        if parsed.vector is not None:
            out.embeddings.append(
                {
                    "dblp_key": paper.dblp_key,
                    "model": EMBEDDING_MODEL,
                    "source": ABSTRACT_SOURCE,
                    "s2_corpus_id": corpus_id,
                    "input_kind": None,
                    "abstract_source": None,
                    "vector": parsed.vector,
                }
            )
        stats["bad_vector"] += parsed.bad_vector
    stats["abstracts"] = len(out.abstracts)
    stats["embeddings"] = len(out.embeddings)
    stats["s2_papers"] = len(out.papers)
    return out


# -- tables --------------------------------------------------------------------------------------

_S = pa.string()
_SCHEMAS: dict[str, pa.Schema] = {
    "stg_s2_lookup": pa.schema(
        [
            ("dblp_key", _S),
            ("status", _S),  # matched | not_found | not_fetched
            ("method", _S),  # doi | title
            ("s2_corpus_id", pa.int64()),
            ("s2_paper_id", _S),
            ("title_similarity", pa.float32()),
            ("s2_dblp_key", _S),
            ("fetched_at", _S),
            ("parser_version", _S),
        ]
    ),
    "stg_s2_paper": pa.schema(
        [
            ("s2_corpus_id", pa.int64()),
            ("s2_paper_id", _S),
            ("title", _S),
            ("year", pa.int32()),
            ("doi", _S),
            ("dblp_key", _S),  # S2's own DBLP key for it; may differ from the DBLP paper's
            ("citation_count", pa.int32()),
            ("influential_citation_count", pa.int32()),
            ("n_references", pa.int32()),  # null when S2 holds no reference list
            ("tldr", _S),
            ("has_abstract", pa.bool_()),
            ("has_embedding", pa.bool_()),
            ("fetched_at", _S),
            ("parser_version", _S),
        ]
    ),
    "stg_s2_reference": pa.schema(
        [
            ("citing_corpus_id", pa.int64()),
            ("cited_corpus_id", pa.int64()),
        ]
    ),
}


def to_arrow(parsed: ParsedS2) -> dict[str, pa.Table]:
    rows = {
        "stg_s2_lookup": parsed.lookup,
        "stg_s2_paper": parsed.papers,
        "stg_s2_reference": parsed.references,
    }
    return {
        name: pa.Table.from_pylist(rows[name], schema=schema) for name, schema in _SCHEMAS.items()
    }


def write_tables(con: duckdb.DuckDBPyConnection, paths: Paths, parsed: ParsedS2) -> None:
    for name, table in to_arrow(parsed).items():
        replace_table(con, name, table, paths.warehouse / "staging" / f"{name}.parquet")
    write_local_abstracts(con, paths, ABSTRACT_SOURCE, parsed.abstracts)
    store.write_source(con, paths, "s2", parsed.embeddings)
