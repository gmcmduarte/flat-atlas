"""The held-out guard (D-61, PLAN §9.4): held-out works never reach any training code.

Held-out works are used for nothing but comparing methods and reporting precision and recall
(P1-08). Every function that fits, calibrates, tunes or seeds something takes its work IDs through
``Guard.check`` (refuses) or ``Guard.drop`` (removes and reports, for seed sets that a human-edited
file fills).
"""

from __future__ import annotations

from collections.abc import Iterable

from flatatlas.taxonomy.schema import GoldFile


class HeldOutLeak(RuntimeError):
    """A held-out work was offered to training, calibration, tuning or seeding."""


class Guard:
    def __init__(self, gold: GoldFile) -> None:
        self.heldout: frozenset[str] = frozenset(w.work for w in gold.works if w.split == "heldout")
        self.labelled: frozenset[str] = frozenset(w.work for w in gold.works)

    def check(self, work_ids: Iterable[str], *, purpose: str) -> None:
        """Raise ``HeldOutLeak`` when any work is held out."""
        bad = sorted(set(work_ids) & self.heldout)
        if bad:
            raise HeldOutLeak(
                f"{len(bad)} held-out work(s) offered to {purpose}: {', '.join(bad[:5])}"
            )

    def drop(self, work_ids: Iterable[str]) -> tuple[list[str], list[str]]:
        """``(kept, dropped)``: the works that may be used, and the held-out ones removed."""
        kept, dropped = [], []
        for w in work_ids:
            (dropped if w in self.heldout else kept).append(w)
        return kept, dropped

    def trainable(self, work_ids: Iterable[str]) -> list[str]:
        """The works of ``work_ids`` that are not held out (sorted)."""
        return sorted(set(work_ids) - self.heldout)
