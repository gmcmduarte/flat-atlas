"""Method (c): the learned fusion, and selection (PLAN §9.4, D-63).

One model over pair features (signals, context features, hierarchy features and the probability of
the topic's best parent). LightGBM (missing values handled natively) or logistic regression (with
missing-value indicators); the simpler one is kept unless the other is clearly better. Isotonic
calibration is fitted on out-of-fold predictions, so a confidence of 0.7 means about 70 % of such
tags are right.

**The hierarchy is soft.** Scoring is two-stage. Stage A scores every pair from its own features.
Stage B adds the best parent's stage-A probability as a feature and scores again, so a child's
score depends on its parents' evidence but nothing is routed away from a branch (no hard top-down
decisions, no error cascade). In training, stage B sees the *out-of-fold* stage-A probabilities, the
same kind of number it will see when it scores new works.

**No held-out leakage.** Every fit goes through ``check_trainable``, which refuses any work with
``split: heldout``. Only random-sample training works fit the calibrator (top-up works are not a
random sample, so they never set a base rate).
"""

from __future__ import annotations

import hashlib
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from flatatlas.tagging.config import TaggerConfig
from flatatlas.tagging.guard import Guard
from flatatlas.tagging.inputs import Corpus, Dag
from flatatlas.tagging.pairs import (
    FEATURES,
    KIND_GOLD_RANDOM,
    PARENT,
    Pairs,
)

STAGE_A_COLUMNS = list(FEATURES)
STAGE_B_COLUMNS = [*FEATURES, PARENT]


class MissingMlExtra(RuntimeError):
    """scikit-learn or lightgbm is not installed."""


def check_trainable(pairs: Pairs, corpus: Corpus, guard: Guard, *, purpose: str) -> None:
    """The one guard every fit goes through: refuse any pair of a held-out work."""
    labelled = pairs.label >= 0
    guard.check({corpus.work_ids[r] for r in pairs.work[labelled]}, purpose=purpose)


# -- the two model families --------------------------------------------------------------------


class LogisticModel:
    """Logistic regression with median imputation, missing indicators and standardisation."""

    kind = "logistic"

    def __init__(self, cfg: TaggerConfig) -> None:
        self.cfg = cfg

    def fit(self, X: np.ndarray, y: np.ndarray, w: np.ndarray) -> LogisticModel:
        try:
            from sklearn.linear_model import LogisticRegression
        except ImportError as exc:  # pragma: no cover
            raise MissingMlExtra("run `uv sync --extra ml`") from exc
        self.missing_cols = [j for j in range(X.shape[1]) if np.isnan(X[:, j]).any()]
        with np.errstate(all="ignore"):
            med = np.nanmedian(X, axis=0)
        self.median = np.nan_to_num(med, nan=0.0)
        Z = self._prepare(X)
        self.mean = Z.mean(axis=0)
        self.std = np.where(Z.std(axis=0) > 1e-9, Z.std(axis=0), 1.0)
        lc = self.cfg.fusion.logistic
        self.model = LogisticRegression(C=lc.C, max_iter=lc.max_iter, solver="lbfgs")
        self.model.fit((Z - self.mean) / self.std, y, sample_weight=w)
        return self

    def _prepare(self, X: np.ndarray) -> np.ndarray:
        nan = np.isnan(X)
        filled = np.where(nan, self.median, X)
        indicators = nan[:, self.missing_cols].astype(np.float32)
        return np.hstack([filled, indicators])

    def predict(self, X: np.ndarray) -> np.ndarray:
        Z = (self._prepare(X) - self.mean) / self.std
        return self.model.predict_proba(Z)[:, 1]

    def contributions(self, x: np.ndarray, names: list[str]) -> list[tuple[str, float]]:
        z = ((self._prepare(x[None, :]) - self.mean) / self.std)[0]
        coefs = self.model.coef_[0]
        labels = [*names, *[f"{names[j]} missing" for j in self.missing_cols]]
        return sorted(zip(labels, z * coefs, strict=True), key=lambda kv: -abs(kv[1]))


class GbmModel:
    """A small LightGBM classifier, deterministic (fixed seed, one thread)."""

    kind = "lightgbm"

    def __init__(self, cfg: TaggerConfig) -> None:
        self.cfg = cfg

    def fit(self, X: np.ndarray, y: np.ndarray, w: np.ndarray) -> GbmModel:
        try:
            import lightgbm as lgb
        except ImportError as exc:  # pragma: no cover
            raise MissingMlExtra("run `uv sync --extra ml`") from exc
        p = self.cfg.fusion.lightgbm
        self.model = lgb.LGBMClassifier(
            n_estimators=p.n_estimators,
            learning_rate=p.learning_rate,
            num_leaves=p.num_leaves,
            min_child_samples=p.min_child_samples,
            subsample=p.subsample,
            subsample_freq=p.subsample_freq,
            colsample_bytree=p.colsample_bytree,
            reg_lambda=p.reg_lambda,
            random_state=self.cfg.seed,
            n_jobs=1,
            deterministic=True,
            force_row_wise=True,
            verbose=-1,
        )
        self.model.fit(X, y, sample_weight=w)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(X)[:, 1]

    def contributions(self, x: np.ndarray, names: list[str]) -> list[tuple[str, float]]:
        raw = self.model.booster_.predict(x[None, :], pred_contrib=True)[0]
        return sorted(zip([*names, "(bias)"], raw, strict=True), key=lambda kv: -abs(kv[1]))


def make_model(kind: str, cfg: TaggerConfig):
    return {"logistic": LogisticModel, "lightgbm": GbmModel}[kind](cfg)


# -- parent probability and folds ----------------------------------------------------------------


def parent_probability(pairs: Pairs, p: np.ndarray) -> np.ndarray:
    """Best-parent probability of every pair (NaN for a root), from probabilities ``p``."""
    out = np.full(len(pairs), np.nan, dtype=np.float32)
    for i, ps in enumerate(pairs.parents):
        if ps:
            out[i] = max(p[j] for j in ps)
    return out


def fold_of(work_id: str, folds: int, seed: int) -> int:
    """The cross-validation fold of a work: a hash of its ID, so folds never depend on order."""
    digest = hashlib.sha256(f"fold:{seed}:{work_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % folds


def _weights(pairs: Pairs, cfg: TaggerConfig) -> np.ndarray:
    return np.where(pairs.kind == 3, cfg.fusion.weight_silver, cfg.fusion.weight_gold)


def _with_parent(X: np.ndarray, parent_p: np.ndarray) -> np.ndarray:
    return np.hstack([X, parent_p[:, None]])


# -- the two-stage model ------------------------------------------------------------------------


@dataclass
class Calibrator:
    """Isotonic regression from a raw probability to a calibrated one."""

    model: object

    def apply(self, p: np.ndarray) -> np.ndarray:
        return np.clip(np.asarray(self.model.predict(p), dtype=np.float64), 0.0, 1.0)


def fit_isotonic(raw: np.ndarray, y: np.ndarray) -> Calibrator:
    try:
        from sklearn.isotonic import IsotonicRegression
    except ImportError as exc:  # pragma: no cover
        raise MissingMlExtra("run `uv sync --extra ml`") from exc
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip", increasing=True)
    iso.fit(raw, y)
    return Calibrator(iso)


@dataclass
class FusionModel:
    kind: str
    stage_a: object
    stage_b: object
    calibrator: Calibrator
    tagger_version: str
    columns: list[str]
    selection: dict | None = None  # threshold and maximum tuned on gold-train (set by `tag fit`)

    def predict(self, pairs: Pairs) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(p_stage_a, parent_p, calibrated)`` for every pair."""
        pa = self.stage_a.predict(pairs.X)
        parent = parent_probability(pairs, pa)
        raw = self.stage_b.predict(_with_parent(pairs.X, parent))
        return pa, parent, self.calibrator.apply(raw)

    def save(self, path: Path) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = pickle.dumps(self, protocol=pickle.HIGHEST_PROTOCOL)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(path)
        return hashlib.sha256(blob).hexdigest()

    @staticmethod
    def load(path: Path) -> FusionModel:
        return pickle.loads(path.read_bytes())  # noqa: S301 - a file this program wrote


def _oof(
    kind: str,
    cfg: TaggerConfig,
    X: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    fold: np.ndarray,
    rows: np.ndarray,
    folds: int,
) -> np.ndarray:
    """Out-of-fold probabilities for ``rows`` (indexes into X); the others are not predicted."""
    out = np.full(len(X), np.nan)
    for k in range(folds):
        test = rows[fold[rows] == k]
        train = rows[fold[rows] != k]
        if len(test) == 0 or len(np.unique(y[train])) < 2:
            continue
        out[test] = make_model(kind, cfg).fit(X[train], y[train], w[train]).predict(X[test])
    return out


def fit_two_stage(
    pairs: Pairs,
    corpus: Corpus,
    guard: Guard,
    cfg: TaggerConfig,
    kind: str,
) -> tuple[FusionModel, dict]:
    """Fit stages A and B and the calibrator on every labelled pair of ``pairs``.

    Out-of-fold (by work) predictions are made inside: stage A's become stage B's parent feature,
    and stage B's, on random-sample gold pairs only, fit the isotonic calibrator.
    Returns the model and a small dictionary of diagnostics.
    """
    check_trainable(pairs, corpus, guard, purpose=f"fit_two_stage({kind})")
    labelled = np.flatnonzero(pairs.label >= 0)
    y = pairs.label.astype(np.float64)
    w = _weights(pairs, cfg)
    folds = cfg.fusion.folds
    fold = np.array(
        [fold_of(corpus.work_ids[r], folds, cfg.seed) for r in pairs.work], dtype=np.int64
    )

    # Stage A, out of fold, for every labelled pair; a final fit on all labelled pairs.
    oof_a = _oof(kind, cfg, pairs.X, y, w, fold, labelled, folds)
    stage_a = make_model(kind, cfg).fit(pairs.X[labelled], y[labelled], w[labelled])
    # Stage A probabilities of every pair: out of fold for labelled pairs (what stage B is trained
    # on), the final model for the others (parents of a labelled pair may be unlabelled).
    p_a = stage_a.predict(pairs.X)
    p_a[labelled] = np.where(np.isnan(oof_a[labelled]), p_a[labelled], oof_a[labelled])
    parent = parent_probability(pairs, p_a)
    XB = _with_parent(pairs.X, parent)

    oof_b = _oof(kind, cfg, XB, y, w, fold, labelled, folds)
    stage_b = make_model(kind, cfg).fit(XB[labelled], y[labelled], w[labelled])

    cal_rows = labelled[(pairs.kind[labelled] == KIND_GOLD_RANDOM) & ~np.isnan(oof_b[labelled])]
    if len(cal_rows) < 50 or len(np.unique(y[cal_rows])) < 2:
        raise RuntimeError(f"too few random-sample pairs to calibrate ({len(cal_rows)})")
    calibrator = fit_isotonic(oof_b[cal_rows], y[cal_rows])
    model = FusionModel(kind, stage_a, stage_b, calibrator, cfg.tagger_version, STAGE_B_COLUMNS)
    info = {
        "n_pairs": int(len(labelled)),
        "n_gold": int(((pairs.kind == 1) | (pairs.kind == 2)).sum()),
        "n_silver": int((pairs.kind == 3).sum()),
        "n_calibration": int(len(cal_rows)),
        "oof_b": oof_b,
    }
    return model, info


# -- selection (PLAN §9.4) ----------------------------------------------------------------


@dataclass
class Selection:
    """The tags of one work: ``(topic, confidence, derived)`` rows and the primary topic."""

    rows: list[tuple[int, float, bool]]
    primary: int | None
    low_confidence: bool = False
    untagged: bool = False


def select_tags(
    prob: dict[int, float],
    dag: Dag,
    *,
    threshold: float,
    max_topics: int,
    fallback_min: float,
) -> Selection:
    """Most specific topics first; ancestors are added as derived rows.

    Keep topics with confidence at or above ``threshold``; drop a topic when one of its descendants
    is also kept (the descendant says it better); keep at most ``max_topics`` of the rest, strongest
    first; mark the strongest ``primary``. Every ancestor of a kept topic is added as a derived row
    with the larger of its own probability and the largest confidence among its kept
    descendants. With nothing above the threshold, the
    best level-0 topic is tagged as a low-confidence tag when its probability reaches
    ``fallback_min``, else the work is untagged.
    """
    kept = {t for t, p in prob.items() if p >= threshold}
    specific = {t for t in kept if not any(d in kept for d in dag.descendants(t))}
    chosen = sorted(specific, key=lambda t: (-prob[t], t))[:max_topics]
    low = False
    if not chosen:
        roots = [(prob[t], t) for t in prob if dag.level[t] == 0]
        if roots:
            p, t = max(roots, key=lambda x: (x[0], -x[1]))
            if p >= fallback_min:
                chosen, low = [t], True
        if not chosen:
            return Selection([], None, untagged=True)
    rows: list[tuple[int, float, bool]] = [(t, prob[t], False) for t in chosen]
    derived: dict[int, float] = {}
    for t in chosen:
        for a in dag.ancestors[t]:
            if a not in chosen:
                derived[a] = max(derived.get(a, 0.0), prob[t])
    rows += [(a, max(p, prob.get(a, 0.0)), True) for a, p in sorted(derived.items())]
    return Selection(rows, chosen[0], low_confidence=low)
