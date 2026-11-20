"""Method (b): the top-down baseline (PLAN §9.4, D-63).

A small classifier per level on the work embeddings, trained on gold-train only: one
one-vs-rest logistic regression per level-0 topic, then one per level-1 topic trained on the works
that carry one of its parents (so it answers "given this branch, is it this child?"). A level-1
probability is the parent's probability times the child's conditional probability (the best over
the parents, since a topic may have several). It exists for the comparison: the errors of a
top-down model cascade (a wrong level-0 guess drags the children down), which is what the soft
hierarchy of method (c) avoids. It scores levels 0 and 1 only, because deeper topics have no labels.

With propagation, the work's level-0 ``prop_cite`` and ``prop_author`` vectors are appended to the
embedding (NaN becomes 0).

Every fit goes through ``Guard.check``; held-out works never train it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from flatatlas.tagging.config import TaggerConfig
from flatatlas.tagging.fusion import fold_of
from flatatlas.tagging.guard import Guard
from flatatlas.tagging.inputs import Corpus, Dag, Labels


def feature_matrix(
    corpus: Corpus, dag: Dag, prop: dict[str, np.ndarray] | None = None
) -> np.ndarray:
    """Embeddings, plus the level-0 columns of the two propagation matrices when given."""
    X = corpus.vectors.astype(np.float64)
    if prop is None:
        return X
    l0 = [t for t in range(dag.n) if dag.level[t] == 0]
    extra = [np.nan_to_num(prop[name][:, l0], nan=0.0) for name in ("prop_cite", "prop_author")]
    return np.hstack([X, *extra])


def _fit_lr(X: np.ndarray, y: np.ndarray, C: float):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(X)
    model = LogisticRegression(C=C, max_iter=300, solver="lbfgs")
    model.fit(scaler.transform(X), y)
    return scaler, model


def _proba(fitted, X: np.ndarray) -> np.ndarray:
    scaler, model = fitted
    return model.predict_proba(scaler.transform(X))[:, 1]


@dataclass
class TopDownModel:
    C: float
    use_prop: bool
    level0: dict[int, object] = field(default_factory=dict)
    level1: dict[int, object] = field(default_factory=dict)
    n_train: int = 0

    def predict(self, X: np.ndarray, dag: Dag) -> dict[int, dict[int, float]]:
        """``{row: {topic: probability}}`` for levels 0 and 1 of every row of ``X``."""
        p0 = {t: _proba(m, X) for t, m in self.level0.items()}
        out: dict[int, dict[int, float]] = {r: {} for r in range(len(X))}
        for t, p in p0.items():
            for r in range(len(X)):
                out[r][t] = float(p[r])
        for t, m in self.level1.items():
            cond = _proba(m, X)
            parents = [q for q in dag.parents[t] if q in p0]
            if not parents:
                continue
            for r in range(len(X)):
                out[r][t] = float(max(p0[q][r] for q in parents) * cond[r])
        return out


def fit(
    corpus: Corpus,
    dag: Dag,
    labels: Labels,
    guard: Guard,
    cfg: TaggerConfig,
    X: np.ndarray,
    works: list[str],
    *,
    use_prop: bool = False,
    C: float | None = None,
) -> TopDownModel:
    """Fit on the gold labels of ``works`` (gold-train; ``Guard`` refuses a held-out work)."""
    guard.check(works, purpose="the top-down classifier")
    c = cfg.topdown
    C = c.C if C is None else C
    rows = np.array([corpus.index[w] for w in works if w in corpus.index], dtype=np.int64)
    kept = [w for w in works if w in corpus.index]
    gold = [{dag.index[x] for x in labels.by_work[w] if x in dag.index} for w in kept]
    model = TopDownModel(C=C, use_prop=use_prop, n_train=len(kept))
    for t in range(dag.n):
        if dag.level[t] != 0:
            continue
        y = np.array([t in g for g in gold], dtype=np.int64)
        if y.sum() >= c.min_positives and (1 - y).sum() >= c.min_negatives:
            model.level0[t] = _fit_lr(X[rows], y, C)
    for t in range(dag.n):
        if dag.level[t] != 1:
            continue
        parents = [q for q in dag.parents[t] if dag.level[q] == 0]
        under = np.array([any(q in g for q in parents) for g in gold])
        y = np.array([t in g for g in gold], dtype=np.int64)
        if under.sum() == 0:
            continue
        ys = y[under]
        if ys.sum() >= c.min_positives and (1 - ys).sum() >= c.min_negatives:
            model.level1[t] = _fit_lr(X[rows[under]], ys, C)
    return model


def cross_validate(
    corpus: Corpus,
    dag: Dag,
    labels: Labels,
    guard: Guard,
    cfg: TaggerConfig,
    X: np.ndarray,
    works: list[str],
    *,
    use_prop: bool = False,
    C: float | None = None,
) -> dict[int, dict[int, float]]:
    """Out-of-fold probabilities of the gold-train ``works`` (same folds as the fusion model)."""
    guard.check(works, purpose="top-down cross-validation")
    folds = cfg.fusion.folds
    fold = {w: fold_of(w, folds, cfg.seed) for w in works}
    out: dict[int, dict[int, float]] = {}
    for k in range(folds):
        train = [w for w in works if fold[w] != k]
        test = [w for w in works if fold[w] == k and w in corpus.index]
        if not test:
            continue
        model = fit(corpus, dag, labels, guard, cfg, X, train, use_prop=use_prop, C=C)
        rows = np.array([corpus.index[w] for w in test], dtype=np.int64)
        preds = model.predict(X[rows], dag)
        for i, r in enumerate(rows.tolist()):
            out[r] = preds[i]
    return out


def predict_all(model: TopDownModel, X: np.ndarray, dag: Dag) -> dict[int, dict[int, float]]:
    return model.predict(X, dag)
