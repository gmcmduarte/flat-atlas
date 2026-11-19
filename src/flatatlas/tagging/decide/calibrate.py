"""Isotonic calibration of the decision model's answers, one calibrator per question type.

The raw probability of the choice question (``dm_l0``) and of the yes/no question (``dm_child``)
is mapped to the share of such answers that were right on gold-train. Only **random-sample**
training works fit a calibrator (top-up works are not a random sample, D-95), only pairs of works
that were actually asked, and held-out works never reach it (``check_trainable`` runs before).

``dm_l0`` is calibrated on level-0 pairs; for a deeper pair the column holds the value of its
best level-0 ancestor and goes through the same map ("how likely is this branch").

Tree models do not change when a feature is mapped through a monotone function, so for LightGBM
calibration only changes what the stored ``dm_*`` columns mean; for the logistic model it matters.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from flatatlas.tagging.fusion import Calibrator, fit_isotonic
from flatatlas.tagging.pairs import FEATURES, KIND_GOLD_RANDOM, Pairs

I_L0 = FEATURES.index("dm_l0")
I_CHILD = FEATURES.index("dm_child")
I_LEVEL = FEATURES.index("t_level")
MIN_PAIRS = 30


@dataclass
class DmCalibrators:
    l0: Calibrator | None
    child: Calibrator | None
    n_l0: int = 0
    n_child: int = 0

    def apply(self, X: np.ndarray) -> np.ndarray:
        """A copy of ``X`` with the two ``dm_*`` columns calibrated (NaN stays NaN)."""
        out = X.copy()
        for col, cal in ((I_L0, self.l0), (I_CHILD, self.child)):
            if cal is None:
                continue
            ok = ~np.isnan(out[:, col])
            out[ok, col] = cal.apply(out[ok, col].astype(np.float64))
        return out


def _fit(raw: np.ndarray, y: np.ndarray) -> Calibrator | None:
    if len(raw) < MIN_PAIRS or len(np.unique(y)) < 2:
        return None
    return fit_isotonic(raw, y)


def fit_dm_calibrators(pairs: Pairs) -> DmCalibrators:
    """Fit on the labelled random-sample gold pairs that carry a raw ``dm_*`` value.

    The caller has run ``check_trainable``; labels of held-out works are already ``-1``.
    """
    rows = np.flatnonzero((pairs.label >= 0) & (pairs.kind == KIND_GOLD_RANDOM))
    X, y = pairs.X, pairs.label.astype(np.float64)
    l0 = rows[(X[rows, I_LEVEL] == 0) & ~np.isnan(X[rows, I_L0])]
    child = rows[(X[rows, I_LEVEL] == 1) & ~np.isnan(X[rows, I_CHILD])]
    return DmCalibrators(
        l0=_fit(X[l0, I_L0].astype(np.float64), y[l0]),
        child=_fit(X[child, I_CHILD].astype(np.float64), y[child]),
        n_l0=len(l0),
        n_child=len(child),
    )
