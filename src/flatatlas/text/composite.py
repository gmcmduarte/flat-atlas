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
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from rapidfuzz import fuzz

MAX_REFERENCES = 10
SEPARATOR = " · "
NEAR_DUPLICATE = 95  # fuzz.ratio of two normalised reference titles (0 to 100)
MAX_NON_LATIN_SHARE = 0.2
# OpenAlex record types that are not a piece of work (journal front matter, errata). Types such as
# "reference-entry" or "software" hold real books and tools, so they stay.
NON_WORK_TYPES = frozenset({"paratext", "editorial", "erratum"})
_REVIEW = re.compile(r"^\s*(book\s+)?reviews?\s+of\b|^\s*(erratum|errata|corrigendum)\b", re.I)
_VOLUME = re.compile(
    r"\bproceedings\b|\blecture notes in\b|\brevised (selected )?papers\b"
    r"|\b\d+(st|nd|rd|th) (international|annual)\b",
    re.I,
)
_NOT_ALNUM = re.compile(r"[^\w]+")
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
    type: str | None = None  # OpenAlex work type, when known


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


_EAST_ASIAN = ("CJK", "HIRAGANA", "KATAKANA", "HANGUL")


def _has_east_asian(text: str) -> bool:
    return any(unicodedata.name(c, "").startswith(_EAST_ASIAN) for c in text)


def _non_latin_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    other = [c for c in letters if not unicodedata.name(c, "").startswith(("LATIN", "GREEK"))]
    return len(other) / len(letters)


def reference_title(ref: Reference) -> str | None:
    """The title to show for a reference, or None when it is not worth showing.

    Dropped (D-86): record types that are not a piece of work (paratext, editorials, errata);
    reviews and errata by title; titles of proceedings volumes and series; titles written mostly
    in a non-Latin script or with any Chinese, Japanese or Korean character (library listings
    such as a textbook's catalogue entry; the model reads English). Trailing dots and quotes
    are stripped.
    """
    if ref.type in NON_WORK_TYPES:
        return None
    title = clean(ref.title).strip(" .\"'")
    if not title or _REVIEW.search(title) or _VOLUME.search(title):
        return None
    if _non_latin_share(title) > MAX_NON_LATIN_SHARE or _has_east_asian(title):
        return None
    return title


def _norm(title: str) -> str:
    return _NOT_ALNUM.sub(" ", title.casefold()).strip()


def choose_references(
    references: Iterable[Reference], limit: int = MAX_REFERENCES
) -> tuple[list[str], int, int]:
    """The titles of up to ``limit`` references by the fixed rule, with the counts.

    Rule (PLAN §9.3): references with a usable title only (``reference_title``); in-corpus first;
    then by how many corpus papers cite them, most first; ties by OpenAlex ID. A title that is
    nearly the same as one already chosen (case, punctuation or a small word apart) is skipped.
    Returns ``(titles, n_references, n_references_with_title)``: the first counts the distinct
    IDs, the second those with a usable title.
    """
    distinct = {r.openalex_id: r for r in references}
    usable = [(r, reference_title(r)) for r in distinct.values()]
    usable = [(r, t) for r, t in usable if t]
    usable.sort(key=lambda rt: (not rt[0].in_corpus, -rt[0].n_citing_in_corpus, rt[0].openalex_id))
    titles: list[str] = []
    seen: list[str] = []
    for _ref, title in usable:
        key = _norm(title)
        if any(fuzz.ratio(key, other) >= NEAR_DUPLICATE for other in seen):
            continue
        seen.append(key)
        titles.append(title)
        if len(titles) == limit:
            break
    return titles, len(distinct), len(usable)


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
