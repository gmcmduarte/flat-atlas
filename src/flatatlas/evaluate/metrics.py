"""Precision, recall, F1, bootstrap intervals and calibration (PLAN §9.6).

Everything resamples **works**, not (work, topic) cells: a work is the unit that was labelled, and
its cells are not independent. The same resamples are used for every method, so a difference
between two methods is a *paired* difference and its interval is honest about the work sample.

Scores are agreement with the labelled set (Claude's reading, D-91, D-93), not truth.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from flatatlas.tagging.inputs import Dag

MIN_POSITIVES = 5  # a topic is in the macro average with at least this many gold positives


@dataclass
class Counts:
    """Per work and topic, the true positives, false positives and false negatives of a level."""

    tp: np.ndarray  # (works, topics) int
    fp: np.ndarray
    fn: np.ndarray

    @property
    def n_works(self) -> int:
        return self.tp.shape[0]


def work_counts(
    predicted: dict[int, set[int]],
    gold: dict[int, set[int]],
    rows: list[int],
    dag: Dag,
    level: int,
) -> Counts:
    """Counts for ``rows`` (in that order) at one level of the DAG."""
    n = len(rows)
    tp = np.zeros((n, dag.n), dtype=np.int32)
    fp = np.zeros_like(tp)
    fn = np.zeros_like(tp)
    for i, r in enumerate(rows):
        pred = {t for t in predicted.get(r, set()) if dag.level[t] == level}
        gold_l = {t for t in gold.get(r, set()) if dag.level[t] == level}
        for t in pred & gold_l:
            tp[i, t] = 1
        for t in pred - gold_l:
            fp[i, t] = 1
        for t in gold_l - pred:
            fn[i, t] = 1
    return Counts(tp, fp, fn)


def prf(tp: float, fp: float, fn: float) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def micro(c: Counts, idx: np.ndarray | None = None) -> tuple[float, float, float]:
    """Micro precision, recall and F1 over the works ``idx`` (all when None; repeats allowed)."""
    if idx is None:
        return prf(c.tp.sum(), c.fp.sum(), c.fn.sum())
    return prf(c.tp[idx].sum(), c.fp[idx].sum(), c.fn[idx].sum())


def macro_topics(c: Counts) -> np.ndarray:
    """The topics in the macro average: at least ``MIN_POSITIVES`` gold positives in the sample."""
    return np.flatnonzero((c.tp.sum(axis=0) + c.fn.sum(axis=0)) >= MIN_POSITIVES)


def macro_f1(c: Counts, idx: np.ndarray | None = None, topics: np.ndarray | None = None) -> float:
    topics = macro_topics(c) if topics is None else topics
    if len(topics) == 0:
        return float("nan")
    sel = slice(None) if idx is None else idx
    tp, fp, fn = (a[sel][:, topics].sum(axis=0) for a in (c.tp, c.fp, c.fn))
    return float(np.mean([prf(a, b, d)[2] for a, b, d in zip(tp, fp, fn, strict=True)]))


METRICS = ("p0", "r0", "f0", "p1", "r1", "f1", "mf0", "mf1", "mean_f")


def metric_values(
    c0: Counts, c1: Counts, idx: np.ndarray | None, topics: tuple
) -> dict[str, float]:
    """The nine reported numbers of one method on the works ``idx``."""
    p0, r0, f0 = micro(c0, idx)
    p1, r1, f1 = micro(c1, idx)
    return {
        "p0": p0, "r0": r0, "f0": f0, "p1": p1, "r1": r1, "f1": f1,
        "mf0": macro_f1(c0, idx, topics[0]), "mf1": macro_f1(c1, idx, topics[1]),
        "mean_f": (f0 + f1) / 2,
    }  # fmt: skip


def resamples(n_works: int, n: int, seed: int) -> np.ndarray:
    """``(n, n_works)`` indexes: ``n`` bootstrap samples of the works, with replacement."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, n_works, size=(n, n_works))


def interval(values: np.ndarray, level: float) -> tuple[float, float]:
    """The central interval holding ``level`` of the values (NaN ignored)."""
    lo, hi = np.nanpercentile(values, [(1 - level) / 2 * 100, (1 + level) / 2 * 100])
    return float(lo), float(hi)


@dataclass
class Estimate:
    value: float
    lo: float
    hi: float


def bootstrap(
    counts: dict[str, tuple[Counts, Counts]], boot: np.ndarray, level: float
) -> dict[str, dict[str, Estimate]]:
    """``{method: {metric: Estimate}}`` with the percentile interval over the shared resamples.

    The macro topics are fixed by the original sample (a topic does not appear and disappear with
    the resample), so macro numbers vary only through the works.
    """
    out: dict[str, dict[str, Estimate]] = {}
    for name, (c0, c1) in counts.items():
        topics = (macro_topics(c0), macro_topics(c1))
        point = metric_values(c0, c1, None, topics)
        draws = {m: np.empty(len(boot)) for m in METRICS}
        for b, idx in enumerate(boot):
            v = metric_values(c0, c1, idx, topics)
            for m in METRICS:
                draws[m][b] = v[m]
        out[name] = {m: Estimate(point[m], *interval(draws[m], level)) for m in METRICS}
    return out


def paired_difference(
    a: tuple[Counts, Counts], b: tuple[Counts, Counts], boot: np.ndarray, level: float
) -> dict[str, Estimate]:
    """Metric of ``a`` minus metric of ``b`` on the same resamples, with its interval."""
    topics = {
        "a": (macro_topics(a[0]), macro_topics(a[1])),
        "b": (macro_topics(b[0]), macro_topics(b[1])),
    }
    point_a, point_b = metric_values(*a, None, topics["a"]), metric_values(*b, None, topics["b"])
    draws = {m: np.empty(len(boot)) for m in METRICS}
    for i, idx in enumerate(boot):
        va, vb = metric_values(*a, idx, topics["a"]), metric_values(*b, idx, topics["b"])
        for m in METRICS:
            draws[m][i] = va[m] - vb[m]
    return {m: Estimate(point_a[m] - point_b[m], *interval(draws[m], level)) for m in METRICS}


def excludes_zero(e: Estimate) -> bool:
    return e.lo > 0 or e.hi < 0


# -- calibration -------------------------------------------------------------------------------


def calibration_curve(
    probs: np.ndarray, truth: np.ndarray, bins: int = 10
) -> list[dict[str, float]]:
    """Stated confidence against observed precision, in equal-width bins of the probability.

    ``probs`` are the method's probabilities for scored (work, topic) pairs and ``truth`` is 1 where
    the pair is a gold label. An empty bin is left out.
    """
    edges = np.linspace(0.0, 1.0, bins + 1)
    which = np.minimum(np.digitize(probs, edges[1:-1]), bins - 1)
    out = []
    for b in range(bins):
        m = which == b
        if m.any():
            out.append(
                {
                    "lo": float(edges[b]),
                    "hi": float(edges[b + 1]),
                    "n": int(m.sum()),
                    "stated": float(probs[m].mean()),
                    "observed": float(truth[m].mean()),
                }
            )
    return out
