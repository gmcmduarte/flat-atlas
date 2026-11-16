"""Attach source records to a DBLP paper (PLAN §8.1).

The harvest stages already looked each paper up (OpenAlex and Semantic Scholar by DOI, then by
title; Crossref by DOI). This module decides, with the rules of §8.1 and the numbers of
``config/resolve.yaml``, whether a returned record really is *this paper*. The join order is:
DOI, then DBLP key against Semantic Scholar's ``externalIds.DBLP``, then the OpenAlex ID the
lookup found, then the fuzzy rule (title similarity and year within a tolerance and a first-author
surname match). A record that fails is dropped and the reason is kept: it is usually another
version of the paper (a journal or CoRR copy), which is what §8.2 is for.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from flatatlas.resolve.config import SourceMatchConfig
from flatatlas.resolve.text import normalise_doi, same_surname, title_similarity

Row = Mapping[str, Any]


@dataclass(frozen=True)
class SourceMatch:
    """A source record accepted as the same publication as a DBLP paper."""

    source: str  # openalex | s2 | crossref
    external_id: str
    method: str  # doi | dblp-key | title
    confidence: float
    title_similarity: float | None = None
    year_diff: int | None = None
    first_author_agrees: bool | None = None  # None: the source gave no authors


@dataclass(frozen=True)
class MatchResult:
    accepted: SourceMatch | None
    rejected: str | None = None  # reason, when a record was returned but not accepted


def _fuzzy(
    paper: Row,
    *,
    source: str,
    external_id: str,
    title: str | None,
    year: int | None,
    first_author: str | None,
    cfg: SourceMatchConfig,
    markers: Sequence[str],
) -> MatchResult:
    sim = title_similarity(paper["title"], title or "", markers)
    if sim < cfg.title_min:
        return MatchResult(None, f"title similarity {sim:.2f} < {cfg.title_min}")
    year_diff = None
    if year is not None and paper.get("year") is not None:
        year_diff = abs(int(year) - int(paper["year"]))
        if year_diff > cfg.year_tolerance:
            return MatchResult(None, f"year differs by {year_diff} (another version?)")
    author_ok: bool | None = None
    confidence = sim
    if cfg.first_author_surname:
        if first_author:
            author_ok = bool(paper.get("first_author")) and same_surname(
                paper["first_author"], first_author
            )
            if not author_ok:
                return MatchResult(None, "first-author surname differs")
        else:
            confidence = min(confidence, cfg.no_author_confidence_cap)
    return MatchResult(
        SourceMatch(source, external_id, "title", confidence, sim, year_diff, author_ok)
    )


def match_openalex(
    paper: Row,
    lookup: Row | None,
    work: Row | None,
    first_author: str | None,
    cfg: SourceMatchConfig,
    markers: Sequence[str] = (),
) -> MatchResult:
    """``lookup`` is the ``stg_openalex_lookup`` row of the paper, ``work`` its OpenAlex work."""
    if lookup is None or not lookup.get("openalex_id") or work is None:
        return MatchResult(None)
    oa_id = lookup["openalex_id"]
    paper_doi = normalise_doi(paper.get("doi"))
    if lookup.get("lookup_kind") == "doi" and paper_doi:
        if normalise_doi(work.get("doi")) == paper_doi:
            return MatchResult(SourceMatch("openalex", oa_id, "doi", 1.0))
        return MatchResult(None, "OpenAlex record carries another DOI")
    return _fuzzy(
        paper,
        source="openalex",
        external_id=oa_id,
        title=work.get("title"),
        year=work.get("publication_year"),
        first_author=first_author,
        cfg=cfg,
        markers=markers,
    )


def match_s2(
    paper: Row,
    lookup: Row | None,
    s2_paper: Row | None,
    cfg: SourceMatchConfig,
    markers: Sequence[str] = (),
) -> MatchResult:
    """``lookup`` is the ``stg_s2_lookup`` row, ``s2_paper`` the S2 paper it points to."""
    if lookup is None or lookup.get("status") != "matched" or s2_paper is None:
        return MatchResult(None)
    corpus_id = str(lookup["s2_corpus_id"])
    paper_doi = normalise_doi(paper.get("doi"))
    if paper_doi and normalise_doi(s2_paper.get("doi")) == paper_doi:
        return MatchResult(SourceMatch("s2", corpus_id, "doi", 1.0))
    if lookup.get("s2_dblp_key") == paper["dblp_key"]:
        return MatchResult(SourceMatch("s2", corpus_id, "dblp-key", 1.0))
    # Semantic Scholar's answers carry no author names here (D-68): the surname rule is waived.
    return _fuzzy(
        paper,
        source="s2",
        external_id=corpus_id,
        title=s2_paper.get("title"),
        year=s2_paper.get("year"),
        first_author=None,
        cfg=cfg,
        markers=markers,
    )


def match_crossref(paper: Row, record: Row | None) -> MatchResult:
    """Crossref is only ever asked by the paper's own DOI, so a row is a match."""
    if record is None or not paper.get("doi"):
        return MatchResult(None)
    if normalise_doi(record.get("doi")) != normalise_doi(paper["doi"]):
        return MatchResult(None, "Crossref record carries another DOI")
    return MatchResult(SourceMatch("crossref", normalise_doi(paper["doi"]) or "", "doi", 1.0))


def share(matches: Sequence[Any]) -> float:
    return sum(1 for m in matches if m) / len(matches) if matches else 0.0
