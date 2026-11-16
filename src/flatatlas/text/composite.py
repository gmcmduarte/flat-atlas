"""The composite text of a work (PLAN §9.3, D-64): the one text every later step reads.

``title · venue · year · titles of up to 10 references · abstract if present · TLDR if present``

Mining (P1-05), the labelled set (P1-06b) and the tagger (P1-07) all call ``build_parts`` /
``compose``; nothing else may build a work's text. It is deterministic: the 10 references are
chosen by a fixed rule (in-corpus references first, then the most cited by corpus papers, ties by
OpenAlex ID), so two runs give the same string.

Abstract and TLDR are local-use data (CLAUDE.md rule 2): the table built from this text lives
under ``warehouse/local/`` and is never exported. The parts are returned separately so that a
caller can weigh them (reference titles count less than the work's own title).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

MAX_REFERENCES = 10
SEPARATOR = " · "
_FORMULA = re.compile(r"\[Formula: see text\]", re.IGNORECASE)
_SPACES = re.compile(r"\s+")


def clean(text: str | None) -> str:
    """Strip placeholders the sources leave in text, and collapse white space."""
    if not text:
        return ""
    return _SPACES.sub(" ", _FORMULA.sub("", text)).strip()


@dataclass(frozen=True)
class Reference:
    """One cited work, as far as the warehouse knows it."""

    openalex_id: str
    title: str | None
    in_corpus: bool  # the cited work is itself a pilot work
    n_citing_in_corpus: int  # how many pilot works cite it


@dataclass(frozen=True)
class WorkInputs:
    work_id: str
    title: str
    venue: str | None = None
    year: int | None = None
    abstract: str | None = None
    abstract_source: str | None = None
    tldr: str | None = None
    references: Sequence[Reference] = field(default_factory=tuple)


@dataclass(frozen=True)
class CompositeParts:
    """The text of one work, part by part. ``text`` joins the parts that exist."""

    work_id: str
    title: str
    venue: str
    year: str
    reference_titles: tuple[str, ...]
    abstract: str
    tldr: str
    n_references: int
    n_references_with_title: int
    abstract_source: str | None

    @property
    def text(self) -> str:
        return compose(self)

    @property
    def has_abstract(self) -> bool:
        return bool(self.abstract)

    @property
    def has_tldr(self) -> bool:
        return bool(self.tldr)


def choose_references(
    references: Iterable[Reference], limit: int = MAX_REFERENCES
) -> tuple[list[str], int, int]:
    """The titles of up to ``limit`` references by the fixed rule, with the counts.

    Rule (PLAN §9.3): references with a title only; in-corpus first; then by how many corpus
    papers cite them, most first; ties by OpenAlex ID. Duplicate IDs and duplicate titles count
    once. Returns ``(titles, n_references, n_references_with_title)`` over the distinct IDs.
    """
    distinct = {r.openalex_id: r for r in references}
    titled = [r for r in distinct.values() if clean(r.title)]
    titled.sort(key=lambda r: (not r.in_corpus, -r.n_citing_in_corpus, r.openalex_id))
    titles: list[str] = []
    seen: set[str] = set()
    for ref in titled:
        title = clean(ref.title)
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        titles.append(title)
        if len(titles) == limit:
            break
    return titles, len(distinct), len(titled)


def build_parts(work: WorkInputs, *, max_references: int = MAX_REFERENCES) -> CompositeParts:
    titles, n_refs, n_titled = choose_references(work.references, max_references)
    abstract = clean(work.abstract)
    return CompositeParts(
        work_id=work.work_id,
        title=clean(work.title),
        venue=clean(work.venue),
        year=str(work.year) if work.year else "",
        reference_titles=tuple(titles),
        abstract=abstract,
        tldr=clean(work.tldr),
        n_references=n_refs,
        n_references_with_title=n_titled,
        abstract_source=work.abstract_source if abstract else None,
    )


def compose(parts: CompositeParts) -> str:
    """Join the parts that exist, in the fixed order."""
    pieces = [parts.title, parts.venue, parts.year]
    if parts.reference_titles:
        pieces.append("References: " + "; ".join(parts.reference_titles))
    if parts.abstract:
        pieces.append(parts.abstract)
    if parts.tldr:
        pieces.append("TLDR: " + parts.tldr)
    return SEPARATOR.join(p for p in pieces if p)
