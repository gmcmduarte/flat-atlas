"""Which works to ask about, and which yes/no questions to ask for a work (PLAN §9.5).

*Unsure works*: a work is sent to the decision model when a level 0 or level 1 pair of the **base**
fusion model (the model without ``dm_*``) has a probability inside ``selection.unsure_band``, or
when two signal families each reach ``noisy_or.agreement.family_min`` for different level-0 topics.
Using the base model keeps the cached answers valid for any later band. For gold-train works the
probabilities passed in are the out-of-fold ones, so a work the model has seen the labels of does
not look more certain than a new one.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from flatatlas.tagging.config import FAMILIES, TaggerConfig
from flatatlas.tagging.inputs import Dag
from flatatlas.tagging.noisyor import evidence


def band_hits(
    by_work: Mapping[int, Mapping[int, float]], dag: Dag, band: tuple[float, float]
) -> set[int]:
    """Corpus rows with a level 0 or 1 pair whose probability is inside ``band``."""
    lo, hi = band
    return {
        r
        for r, probs in by_work.items()
        if any(lo <= p <= hi for t, p in probs.items() if dag.level[t] <= 1)
    }


def disagreement_rows(matrices: Mapping[str, np.ndarray], dag: Dag, cfg: TaggerConfig) -> set[int]:
    """Rows where two signal families back different level-0 topics (each at ``family_min``)."""
    l0 = [t for t in range(dag.n) if dag.level[t] == 0]
    weights = cfg.noisy_or.weights
    minimum = cfg.noisy_or.agreement.family_min
    n = next(iter(matrices.values())).shape[0]
    best = np.full((n, len(FAMILIES)), -1, dtype=np.int64)
    ok = np.zeros((n, len(FAMILIES)), dtype=bool)
    for f, members in enumerate(FAMILIES.values()):
        score = np.maximum.reduce(
            [
                weights.get(m, 0.0) * evidence(m, matrices[m][:, l0], cfg)
                for m in members
                if m in matrices
            ]
        )
        best[:, f] = score.argmax(axis=1)
        ok[:, f] = score.max(axis=1) >= minimum
    out: set[int] = set()
    for r in range(n):
        picked = {int(best[r, f]) for f in range(len(FAMILIES)) if ok[r, f]}
        if len(picked) > 1:
            out.add(r)
    return out


def child_questions(
    l0_probs: Mapping[int, float],
    base_p: Mapping[int, float],
    shortlisted: set[int],
    dag: Dag,
    *,
    top_l0: int,
    max_level: int,
    cap: int,
) -> list[int]:
    """Topics to ask yes/no about for one work, most useful first, at most ``cap``.

    The children of the ``top_l0`` most probable level-0 topics, plus the shortlisted topics at
    levels 1 to ``max_level`` anywhere (a strong candidate under another branch is still asked
    about, so a wrong top-level choice does not hide it). Order: under a top topic first, then
    shortlisted, then base probability; ties by topic index.
    """
    top = sorted(l0_probs, key=lambda t: (-l0_probs[t], t))[:top_l0]
    under = {c for t in top for c in dag.children[t] if 1 <= dag.level[c] <= max_level}
    cand = under | {t for t in shortlisted if 1 <= dag.level[t] <= max_level}
    ranked = sorted(
        cand, key=lambda t: (t in under, t in shortlisted, base_p.get(t, 0.0), -t), reverse=True
    )
    return ranked[:cap]
