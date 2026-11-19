"""Cross-validated precision, recall and F1 on gold-train (PLAN §9.6), and threshold tuning.

**No held-out number is computed here.** Every function takes the work list it scores; callers
pass gold-train works only, and ``Guard.check`` refuses a held-out one. Scores are *agreement with
the labelled set*, which is Claude's reading of the papers (D-91, D-93).

Predicted tags at level 0 or level 1 are the selected topics plus their derived ancestors at that
level; gold tags are the labels at that level. Micro scores pool all (work, topic) cells. Macro
scores average over topics that have at least ``MIN_POSITIVES`` gold positives in the evaluated
works (the thinner topics are listed, not scored).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from flatatlas.tagging.config import TaggerConfig
from flatatlas.tagging.fusion import (
    fit_two_stage,
    fold_of,
    select_tags,
)
from flatatlas.tagging.guard import Guard
from flatatlas.tagging.inputs import Corpus, Dag, Labels
from flatatlas.tagging.pairs import Pairs

MIN_POSITIVES = 5


@dataclass
class Scores:
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int
    macro_f1: float | None = None
    n_macro_topics: int = 0
    n_thin_topics: int = 0


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def work_probabilities(pairs: Pairs, prob: np.ndarray) -> dict[int, dict[int, float]]:
    """``{corpus row: {topic: probability}}`` from per-pair probabilities."""
    out: dict[int, dict[int, float]] = {}
    for r, t, p in zip(pairs.work.tolist(), pairs.topic.tolist(), prob.tolist(), strict=True):
        out.setdefault(r, {})[t] = p
    return out


def predict_sets(
    by_work: dict[int, dict[int, float]],
    rows: list[int],
    dag: Dag,
    *,
    threshold: float,
    max_topics: int,
    fallback_min: float,
) -> dict[int, set[int]]:
    """The predicted topics (non-derived and derived) of each work in ``rows``."""
    out: dict[int, set[int]] = {}
    for r in rows:
        sel = select_tags(
            by_work.get(r, {}),
            dag,
            threshold=threshold,
            max_topics=max_topics,
            fallback_min=fallback_min,
        )
        out[r] = {t for t, _p, _d in sel.rows}
    return out


def score_level(
    predicted: dict[int, set[int]],
    gold: dict[int, set[int]],
    dag: Dag,
    level: int,
    *,
    min_positives: int = MIN_POSITIVES,
) -> Scores:
    tp = fp = fn = 0
    per_topic: dict[int, list[int]] = {}
    for r, g in gold.items():
        pred = {t for t in predicted.get(r, set()) if dag.level[t] == level}
        gold_l = {t for t in g if dag.level[t] == level}
        for t in pred | gold_l:
            c = per_topic.setdefault(t, [0, 0, 0])
            if t in pred and t in gold_l:
                tp += 1
                c[0] += 1
            elif t in pred:
                fp += 1
                c[1] += 1
            else:
                fn += 1
                c[2] += 1
    p, rcl, f = _prf(tp, fp, fn)
    macro, thin = [], 0
    for c in per_topic.values():
        if c[0] + c[2] >= min_positives:
            macro.append(_prf(*c)[2])
        elif c[0] + c[2] > 0:
            thin += 1
    return Scores(
        p,
        rcl,
        f,
        tp,
        fp,
        fn,
        macro_f1=float(np.mean(macro)) if macro else None,
        n_macro_topics=len(macro),
        n_thin_topics=thin,
    )


def gold_sets(labels: Labels, corpus: Corpus, dag: Dag, works: list[str]) -> dict[int, set[int]]:
    return {
        corpus.index[w]: {dag.index[x] for x in labels.by_work[w] if x in dag.index}
        for w in works
        if w in corpus.index
    }


def unsure_share(
    by_work: dict[int, dict[int, float]], rows: list[int], dag: Dag, band: tuple[float, float]
) -> float:
    """Share of works with a level 0 or level 1 pair inside the unsure band."""
    lo, hi = band
    n = 0
    for r in rows:
        probs = by_work.get(r, {})
        if any(lo <= p <= hi for t, p in probs.items() if dag.level[t] <= 1):
            n += 1
    return n / max(len(rows), 1)


def tune_selection(
    by_work: dict[int, dict[int, float]],
    gold: dict[int, set[int]],
    dag: Dag,
    cfg: TaggerConfig,
) -> dict:
    """The threshold and maximum that give the best mean of the level 0 and level 1 micro F1."""
    s = cfg.selection
    best: dict | None = None
    rows = sorted(gold)
    for thr in s.tune_threshold:
        for mx in s.tune_max_topics:
            pred = predict_sets(
                by_work, rows, dag, threshold=thr, max_topics=mx, fallback_min=s.fallback_min
            )
            f0 = score_level(pred, gold, dag, 0).f1
            f1 = score_level(pred, gold, dag, 1).f1
            mean = (f0 + f1) / 2
            if best is None or mean > best["f1_mean"] + 1e-12:
                best = {
                    "threshold": thr,
                    "max_topics": mx,
                    "f1_mean": mean,
                    "f1_l0": f0,
                    "f1_l1": f1,
                }
    assert best is not None
    return best


def cross_validate(
    pairs: Pairs,
    corpus: Corpus,
    labels: Labels,
    guard: Guard,
    cfg: TaggerConfig,
    kind: str,
    *,
    eval_works: list[str],
) -> dict[int, dict[int, float]]:
    """Out-of-fold calibrated probabilities for the pairs of ``eval_works`` (gold-train only).

    For each fold k, the model is fitted on every labelled pair except the gold pairs of fold-k
    works, then scores the fold-k works. Silver pairs are all kept: they are not in ``gold.yaml``.
    """
    guard.check(eval_works, purpose="cross-validation scoring")
    folds = cfg.fusion.folds
    rows_of = {w: corpus.index[w] for w in eval_works if w in corpus.index}
    fold_rows: dict[int, set[int]] = {k: set() for k in range(folds)}
    for w, r in rows_of.items():
        fold_rows[fold_of(w, folds, cfg.seed)].add(r)
    gold_kinds = (pairs.kind == 1) | (pairs.kind == 2)
    out: dict[int, dict[int, float]] = {}
    for k in range(folds):
        held = np.isin(pairs.work, np.fromiter(fold_rows[k], dtype=np.int64))
        label = pairs.label.copy()
        label[held & gold_kinds] = -1
        train_pairs = replace(pairs, label=label)
        model, _info = fit_two_stage(train_pairs, corpus, guard, cfg, kind)
        _pa, _parent, cal = model.predict(pairs)
        sub = np.flatnonzero(held)
        for i in sub:
            out.setdefault(int(pairs.work[i]), {})[int(pairs.topic[i])] = float(cal[i])
    return out
