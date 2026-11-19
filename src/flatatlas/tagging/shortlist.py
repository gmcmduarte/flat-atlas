"""The shortlist (PLAN §9.3): about 8 candidate topics per work, plus their ancestors.

The union of the best candidates of each signal family (lexical, seed embedding, description
embedding, source), filled up to ``size`` by the noisy-or score. Later steps only score
shortlisted pairs. Its recall on gold-train is a number we report: a label the shortlist misses can
never be recovered.
"""

from __future__ import annotations

import numpy as np

from flatatlas.tagging.config import TaggerConfig
from flatatlas.tagging.inputs import Dag, Labels
from flatatlas.tagging.signals import Signals


def _top(scores: np.ndarray, k: int, minimum: float) -> list[int]:
    """Indexes of the ``k`` best cells above ``minimum`` (ties by topic index, stable)."""
    order = np.argsort(-scores, kind="stable")[:k]
    return [int(i) for i in order if scores[i] > minimum]


def shortlist(sig: Signals, p_noisy: np.ndarray, cfg: TaggerConfig) -> np.ndarray:
    """Boolean ``(works, topics)`` matrix: the candidate topics of each work."""
    m = sig.matrices
    quota = cfg.shortlist.per_family
    lexical = np.nan_to_num(
        np.maximum.reduce([m["lex_title"], m["lex_abstract"], m["lex_refs"]]), nan=0.0
    )
    seed = np.nan_to_num(m["emb_seed"], nan=0.0)
    desc = np.nan_to_num(m["emb_desc"], nan=0.0)
    source = np.nan_to_num(m["src_openalex"], nan=0.0)
    floor = cfg.shortlist.min_percentile
    n = lexical.shape[0]
    out = np.zeros(lexical.shape, dtype=bool)
    for row in range(n):
        picked: list[int] = []
        for scores, k, minimum in (
            (lexical[row], quota["lexical"], 0.0),
            (seed[row], quota["emb_seed"], floor),
            (desc[row], quota["emb_desc"], floor),
            (source[row], quota["source"], 0.0),
        ):
            for t in _top(scores, k, minimum):
                if t not in picked:
                    picked.append(t)
        size = cfg.shortlist.size
        if len(picked) > size:  # keep the best by the noisy-or score
            picked = sorted(picked, key=lambda t: (-p_noisy[row, t], t))[:size]
        elif len(picked) < size:
            for t in _top(p_noisy[row], size, 0.0):
                if t not in picked:
                    picked.append(t)
                if len(picked) == size:
                    break
        out[row, picked] = True
    return out


def with_ancestors(candidates: np.ndarray, dag: Dag) -> np.ndarray:
    """The candidates plus all their ancestors."""
    closed = candidates.copy()
    for t in range(dag.n):
        if dag.ancestors[t]:
            rows = candidates[:, t]
            for a in dag.ancestors[t]:
                closed[rows, a] = True
    return closed


def recall(
    closed: np.ndarray, corpus_index: dict[str, int], dag: Dag, labels: Labels, works: list[str]
) -> dict:
    """Share of gold labels (levels 0 and 1) that are in the shortlist or its ancestors."""
    total = {0: 0, 1: 0}
    found = {0: 0, 1: 0}
    misses: list[tuple[str, str]] = []
    for w in works:
        row = corpus_index.get(w)
        if row is None:
            continue
        for label in labels.by_work[w]:
            t = dag.index.get(label)
            if t is None:
                continue
            lv = int(dag.level[t])
            total[lv] += 1
            if closed[row, t]:
                found[lv] += 1
            else:
                misses.append((w, label))
    both_total = sum(total.values())
    return {
        "level0": found[0] / max(total[0], 1),
        "level1": found[1] / max(total[1], 1),
        "all": sum(found.values()) / max(both_total, 1),
        "n": both_total,
        "misses": misses,
    }


def miss_causes(
    sig: Signals,
    misses: list[tuple[str, str]],
    corpus_index: dict[str, int],
    dag: Dag,
    cfg: TaggerConfig,
) -> dict[str, int]:
    """Why each missed label was missed, by the strongest evidence it had.

    ``lexical hit not picked``: a phrase matched but other topics filled the lexical quota;
    ``embedding above floor not picked``: a percentile at or above ``min_percentile`` lost out;
    ``source hit not picked``; otherwise ``no signal above its floor``: the label is not
    recoverable from phrases or from the embedding, which is a limit of the signals.
    """
    m = sig.matrices
    floor = cfg.shortlist.min_percentile
    causes: dict[str, int] = {}
    for work, label in misses:
        row, t = corpus_index[work], dag.index[label]
        lex = max(
            float(np.nan_to_num(m[k][row, t])) for k in ("lex_title", "lex_abstract", "lex_refs")
        )
        emb = max(float(np.nan_to_num(m[k][row, t])) for k in ("emb_seed", "emb_desc"))
        src = float(np.nan_to_num(m["src_openalex"][row, t]))
        if lex > 0:
            cause = "lexical hit not picked"
        elif emb >= floor:
            cause = "embedding above floor not picked"
        elif src > 0:
            cause = "source hit not picked"
        else:
            cause = "no signal above its floor"
        key = f"level {int(dag.level[t])}: {cause}"
        causes[key] = causes.get(key, 0) + 1
    return dict(sorted(causes.items()))
