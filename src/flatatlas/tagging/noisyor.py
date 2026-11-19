"""Method (a): transparent weighted fusion (PLAN §9.4).

``confidence = noisy_or(w_i * s_i)`` over the signals, plus an agreement bonus when at least two
independent signal families (lexical, embedding, source) each reach ``family_min``. The venue
prior is a weak tie-breaker and never counts as a family. A missing signal counts as zero.
Embedding percentiles are first turned into evidence: nothing below ``percentile_floor`` counts.
"""

from __future__ import annotations

import numpy as np

from flatatlas.tagging.config import FAMILIES, TaggerConfig


def evidence(name: str, values: np.ndarray, cfg: TaggerConfig) -> np.ndarray:
    """A signal as evidence in [0, 1]; NaN becomes 0."""
    v = np.nan_to_num(values.astype(np.float64), nan=0.0)
    if name in ("emb_seed", "emb_desc"):
        floor = cfg.signals.percentile_floor
        v = np.clip((v - floor) / (1.0 - floor), 0.0, 1.0)
    return v


def noisy_or(matrices: dict[str, np.ndarray], cfg: TaggerConfig) -> np.ndarray:
    """Confidence of every cell of the signal matrices (any shape)."""
    weights = cfg.noisy_or.weights
    agree = cfg.noisy_or.agreement
    shape = next(iter(matrices.values())).shape
    miss = np.ones(shape)
    weighted: dict[str, np.ndarray] = {}
    for name, values in matrices.items():
        w = weights.get(name, 0.0)
        contribution = w * evidence(name, values, cfg)
        weighted[name] = contribution
        miss *= 1.0 - contribution
    p = 1.0 - miss
    agreeing = np.zeros(shape)
    for members in FAMILIES.values():
        best = np.maximum.reduce([weighted[m] for m in members if m in weighted])
        agreeing += best >= agree.family_min
    extra = np.maximum(agreeing - 1.0, 0.0)
    return 1.0 - (1.0 - p) * (1.0 - agree.bonus) ** extra
