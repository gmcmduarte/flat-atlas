"""Text rules shared by the resolve modules: titles, names, DOIs (PLAN §8.1 to §8.3).

``title_similarity`` is a token-sort ratio, not the token-set ratio PLAN §8.1 names: the set
ratio returns 1.0 whenever one title's words are contained in the other's ("Isometric words"
against "Hypercubes and isometric words"), which would merge a paper with any longer title.
Recorded as D-73.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence

from rapidfuzz import fuzz

from flatatlas.ids import normalise_anchor

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_HOMONYM_SUFFIX = re.compile(r"\s+\d{4}$")
_ROMAN = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")


def normalise_doi(doi: str | None) -> str | None:
    """Lower-case DOI without a resolver prefix; ``None`` for an empty value."""
    if not doi or not doi.strip():
        return None
    return normalise_anchor("doi", doi)[1]


def fold(text: str) -> str:
    """Lower-case, accents removed, dashes unified, punctuation turned into spaces."""
    text = text.translate(_DASHES)
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    stripped = _NON_WORD.sub(" ", stripped.lower())
    return _SPACES.sub(" ", stripped).strip()


def strip_markers(title: str, markers: Iterable[str]) -> str:
    """Remove "(extended abstract)", ": full version" and the like from a title."""
    result = title
    for marker in markers:
        escaped = re.escape(marker)
        # parenthesised or bracketed anywhere, or after a colon / dash / comma at the end
        result = re.sub(rf"[\(\[]\s*{escaped}\s*[\)\]]", " ", result, flags=re.IGNORECASE)
        result = re.sub(rf"\s*[:\-–—,]\s*{escaped}\s*\.?\s*$", " ", result, flags=re.I)
    return _SPACES.sub(" ", result).strip()


def title_key(title: str, markers: Iterable[str] = ()) -> str:
    """The comparison form of a title."""
    return fold(strip_markers(title, markers))


def title_similarity(a: str, b: str, markers: Iterable[str] = ()) -> float:
    """0 to 1; 1.0 means equal after folding and marker removal."""
    ka, kb = title_key(a, markers), title_key(b, markers)
    if not ka or not kb:
        return 0.0
    return fuzz.token_sort_ratio(ka, kb) / 100.0


def numbering_tokens(title: str) -> frozenset[str]:
    """Roman numerals and digits that number a title ("... II", "Part 2", "(1)")."""
    tokens = fold(title).split()
    return frozenset(t for t in tokens if t in _ROMAN or t.isdigit())


def numbering_differs(a: str, b: str) -> bool:
    """True if two similar titles carry different part numbers, so they are different works."""
    return numbering_tokens(a) != numbering_tokens(b)


def clean_person_name(name: str) -> str:
    """A DBLP name without the homonym number ("Nina Yevtushenko 0001")."""
    return _HOMONYM_SUFFIX.sub("", name.strip())


_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def _name_tokens(name: str) -> list[str]:
    return fold(clean_person_name(name)).split()


def surname(name: str) -> str:
    """Last word of the folded name, ignoring a generation suffix ("Karel Culik II" -> culik)."""
    parts = [t for t in _name_tokens(name) if t not in _NAME_SUFFIXES]
    return parts[-1] if parts else ""


def same_surname(dblp_name: str, other_name: str) -> bool:
    """Does the DBLP author's surname appear among the words of another source's spelling?

    Sources order and decorate names differently ("Buchholz, Thomas", "Sakthi Balan Muthiah",
    "Lila Kari A"), so the test is containment, not equality of the last word.
    """
    wanted = surname(dblp_name)
    return bool(wanted) and wanted in _name_tokens(other_name)


def name_similarity(a: str, b: str) -> float:
    """How likely two spellings are the same person on one paper (0 to 1).

    Full-name token-sort ratio, raised to 0.9 when the surnames agree and one first name is just
    the other's initial ("J. Smith" against "John Smith"), or when all the full words (not
    initials) of the shorter spelling occur in the longer one and there are at least two of them
    ("Zeki Bayram" in "Zeki O. Bayram", "M. Sakthi Balan" in "Sakthi Balan Muthiah"). Enough to
    align the authors of one paper; never used to create or merge an author.
    """
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return 0.0
    score = fuzz.token_sort_ratio(" ".join(ta), " ".join(tb)) / 100.0
    initial_only = len(ta[0]) == 1 or len(tb[0]) == 1
    if ta[-1] == tb[-1] and ta[0][0] == tb[0][0] and initial_only:
        score = max(score, 0.9)
    words_a = {t for t in ta if len(t) > 1}
    words_b = {t for t in tb if len(t) > 1}
    shorter, longer = (words_a, words_b) if len(words_a) <= len(words_b) else (words_b, words_a)
    if len(shorter) >= 2 and shorter <= longer:
        score = max(score, 0.9)
    return score


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def page_count(pages: str | None) -> int | None:
    """Number of pages from "177-188" (inclusive); ``None`` when it cannot be told."""
    if not pages:
        return None
    match = re.fullmatch(r"\s*(\d+)\s*[-–]\s*(\d+)\s*", pages)
    if not match:
        return None
    first, last = int(match.group(1)), int(match.group(2))
    return last - first + 1 if last >= first else None


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine of two vectors; 0.0 when one is all zeros."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0
