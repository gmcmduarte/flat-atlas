"""Phrase matching on normalised text, on word boundaries (PLAN §9.3).

Text and phrases are turned into the same token sequences: case and accents folded, Greek letters
spelled out, hyphens split (so "finite-state" and "finite state" are one phrase), British spelling
made American, plural forms made singular. A phrase matches where its tokens appear as a run, so
there are no matches inside words. A phrase may carry *context words*: it counts only when one of
them occurs in the work's own text. Everything is a dictionary lookup over n-grams: fast enough
for the whole pilot in a second or two, and for a weekly batch in less.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from flatatlas.taxonomy.phrases import american, fold, singular

_TOKEN = re.compile(r"[^\W_]+")


def stem(word: str) -> str:
    return singular(american(word)) if word.isalpha() else word


def tokenise(text: str) -> list[str]:
    """The normalised token sequence of a text."""
    return [stem(w) for w in _TOKEN.findall(fold(text or ""))]


@dataclass(frozen=True)
class PhraseEntry:
    topic: int  # index into the DAG
    tokens: tuple[str, ...]
    weight: float
    context: frozenset[str] = frozenset()
    kind: str = "include"  # include | alias | name | variant | neighbour


@dataclass(frozen=True)
class Match:
    entry: PhraseEntry
    start: int
    end: int  # exclusive


class Matcher:
    """A dictionary of phrase entries, matched against token sequences."""

    def __init__(self, entries: Iterable[PhraseEntry]) -> None:
        self.entries: list[PhraseEntry] = []
        self._index: dict[tuple[str, ...], list[PhraseEntry]] = {}
        seen: set[tuple[int, tuple[str, ...]]] = set()
        for e in entries:
            if not e.tokens or (e.topic, e.tokens) in seen:
                continue
            seen.add((e.topic, e.tokens))
            self.entries.append(e)
            self._index.setdefault(e.tokens, []).append(e)
        self.max_n = max((len(t) for t in self._index), default=0)

    def __len__(self) -> int:
        return len(self.entries)

    def find(self, tokens: Sequence[str], context: frozenset[str] | set[str] | None = None):
        """All matches in ``tokens``; ``context`` is the token set that context words come from.

        When ``context`` is None the phrase's own tokens are the only evidence, so a phrase that
        needs a context word never matches.
        """
        out: list[Match] = []
        n_tokens = len(tokens)
        for n in range(1, min(self.max_n, n_tokens) + 1):
            for i in range(n_tokens - n + 1):
                for entry in self._index.get(tuple(tokens[i : i + n]), ()):
                    if entry.context and not (context and entry.context & context):
                        continue
                    out.append(Match(entry, i, i + n))
        return out


def context_tokens(*texts: str) -> frozenset[str]:
    out: set[str] = set()
    for t in texts:
        out.update(tokenise(t))
    return frozenset(out)
