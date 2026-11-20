"""Topic graph and the roll-up of tags to topics (PLAN §9.4, "volume for bubbles").

``m_t(w)`` is the largest confidence among the non-derived tags of work *w* whose topic is *t* or a
descendant of *t*. The maximum is what stops a work from counting twice inside an ancestor: two
tags under one parent give the parent the larger of the two, and a diamond (G above P1 and P2,
both above c) gives G the confidence of c once.

Work classes (D-102): ``tagged`` (a normal tag), ``low_confidence`` (only the level-0 fallback tag
below the selection threshold) and ``untagged`` (no tag).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

TAGGED = "tagged"
LOW_CONFIDENCE = "low_confidence"
UNTAGGED = "untagged"


@dataclass(frozen=True)
class TopicGraph:
    """The topic DAG as index lists (``parents[i]`` are the indices of topic *i*'s parents)."""

    ids: list[str]
    parents: list[list[int]]

    @classmethod
    def from_parents(cls, parent_ids: dict[str, Sequence[str]]) -> TopicGraph:
        """Build from ``{topic_id: [parent ids]}``; the order of the keys is the index order."""
        ids = list(parent_ids)
        index = {t: i for i, t in enumerate(ids)}
        parents = [[index[p] for p in parent_ids[t] if p in index] for t in ids]
        return cls(ids, parents)

    @property
    def n(self) -> int:
        return len(self.ids)

    @property
    def index(self) -> dict[str, int]:
        return {t: i for i, t in enumerate(self.ids)}

    @property
    def children(self) -> list[list[int]]:
        out: list[list[int]] = [[] for _ in self.ids]
        for i, ps in enumerate(self.parents):
            for p in ps:
                out[p].append(i)
        return out

    @property
    def ancestors(self) -> list[frozenset[int]]:
        """All ancestors of each topic, not including the topic itself."""
        memo: dict[int, frozenset[int]] = {}

        def up(i: int) -> frozenset[int]:
            if i not in memo:
                acc: set[int] = set()
                for p in self.parents[i]:
                    acc.add(p)
                    acc |= up(p)
                memo[i] = frozenset(acc)
            return memo[i]

        return [up(i) for i in range(self.n)]

    @property
    def descendants(self) -> list[frozenset[int]]:
        """All descendants of each topic, not including the topic itself."""
        out: list[set[int]] = [set() for _ in self.ids]
        for i, anc in enumerate(self.ancestors):
            for a in anc:
                out[a].add(i)
        return [frozenset(s) for s in out]

    @property
    def levels(self) -> list[int]:
        """Shortest distance to a root (D-80)."""
        memo: dict[int, int] = {}

        def lv(i: int) -> int:
            if i not in memo:
                memo[i] = 0 if not self.parents[i] else 1 + min(lv(p) for p in self.parents[i])
            return memo[i]

        return [lv(i) for i in range(self.n)]

    def related_mask(self) -> np.ndarray:
        """``mask[a, b]`` is True for the same topic or an ancestor-descendant pair.

        Lateral edges are never computed for these pairs (PLAN §4.3).
        """
        mask = np.eye(self.n, dtype=bool)
        for i, anc in enumerate(self.ancestors):
            for a in anc:
                mask[i, a] = True
                mask[a, i] = True
        return mask


def base_matrix(
    work_index: dict[str, int],
    topic_index: dict[str, int],
    tags: Iterable[tuple[str, str, float, bool]],
) -> np.ndarray:
    """Works x topics matrix of the non-derived tag confidences (largest wins on a repeat).

    ``tags`` are ``(work_id, topic_id, confidence, derived)``; derived rows are skipped and rows of
    unknown works or topics are ignored (a work outside the table has no tags).
    """
    base = np.zeros((len(work_index), len(topic_index)), dtype=np.float32)
    for work_id, topic_id, confidence, derived in tags:
        if derived:
            continue
        w = work_index.get(work_id)
        t = topic_index.get(topic_id)
        if w is None or t is None:
            continue
        base[w, t] = max(base[w, t], confidence)
    return base


def roll_up(base: np.ndarray, graph: TopicGraph) -> np.ndarray:
    """``m[w, t]``: the largest base confidence in the subtree of *t* (itself included)."""
    m = base.copy()
    for t, desc in enumerate(graph.descendants):
        if desc:
            cols = sorted(desc)
            m[:, t] = np.maximum(m[:, t], base[:, cols].max(axis=1))
    return m


def work_classes(
    work_ids: Sequence[str], flags: dict[str, set[str]], tagged_works: set[str]
) -> list[str]:
    """The class of every work, in the order of ``work_ids``.

    ``tagged_works`` holds the works with at least one tag row; ``flags`` maps a work to the flags
    on its rows. A work whose only tags carry ``low_confidence`` is ``low_confidence``.
    """
    out = []
    for w in work_ids:
        if w not in tagged_works:
            out.append(UNTAGGED)
        elif "low_confidence" in flags.get(w, set()):
            out.append(LOW_CONFIDENCE)
        else:
            out.append(TAGGED)
    return out
