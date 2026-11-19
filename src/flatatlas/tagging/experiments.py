"""The two small experiments of P1-07, judged on gold-train by cross-validation.

1. ``emb_desc``: the SPECTER2 proximity adapter, the SPECTER2 ad-hoc *query* adapter, or one small
   general sentence-transformers model for the topic descriptions.
2. For works without a Semantic Scholar vector: the local SPECTER2 vector from the stored input,
   from the title alone, or from the title plus the reference titles.

Two numbers are reported for each variant: the average precision of the one signal on gold-train
level 0 and level 1 labels (pooled over work-topic pairs; works are random-sample training works)
and the cross-validated F1 of the whole learned fusion (LightGBM, selection tuned on gold-train).
Both read only gold-train works. No held-out number is computed.
"""

from __future__ import annotations

import numpy as np

from flatatlas.tagging import descriptions, evaluate, local_embed, runner
from flatatlas.tagging.runner import Context


def average_precision(y: np.ndarray, score: np.ndarray) -> float:
    """Average precision of one score against 0/1 labels (ties broken by order, NaN is 0)."""
    score = np.nan_to_num(score, nan=-1.0)
    order = np.argsort(-score, kind="stable")
    y = y[order]
    hits = np.cumsum(y)
    precision = hits / (np.arange(len(y)) + 1)
    return float((precision * y).sum() / max(y.sum(), 1))


def _signal_ap(ctx: Context, signal: str, rows: list[int]) -> dict:
    dag = ctx.dag
    mask = dag.level <= 1
    gold = np.zeros((len(rows), dag.n))
    inv = {r: i for i, r in enumerate(rows)}
    for w, labs in ctx.labels.by_work.items():
        r = ctx.corpus.index.get(w)
        if r in inv:
            for lab in labs:
                if lab in dag.index:
                    gold[inv[r], dag.index[lab]] = 1
    values = ctx.sig.matrices[signal][rows]
    out = {}
    for name, sel in (("level0", dag.level == 0), ("level1", dag.level == 1), ("both", mask)):
        out[name] = round(average_precision(gold[:, sel].ravel(), values[:, sel].ravel()), 4)
    return out


def _cv_f1(ctx: Context, rows_filter: set[int] | None = None) -> dict:
    cfg, dag = ctx.cfg, ctx.dag
    train = ctx.labels.works(split="train")
    random_train = ctx.labels.works(split="train", sampling="random")
    probs = evaluate.cross_validate(
        ctx.pairs, ctx.corpus, ctx.labels, ctx.guard, cfg, "lightgbm", eval_works=train
    )
    out = {}
    for name, works in (("random_train", random_train), ("all_train", train)):
        gold = evaluate.gold_sets(ctx.labels, ctx.corpus, dag, works)
        if rows_filter is not None:
            gold = {r: g for r, g in gold.items() if r in rows_filter}
        if not gold:
            continue
        tuned = evaluate.tune_selection(probs, gold, dag, cfg)
        out[name] = runner.level_report(probs, gold, dag, cfg, tuned)
    return out


def emb_desc(ctx_factory, models=descriptions.MODELS) -> dict:
    """Experiment 1. ``ctx_factory(desc_space)`` builds a context for one description model."""
    results: dict = {}
    for model in models:
        try:
            ctx = ctx_factory(model)
        except Exception as exc:  # noqa: BLE001 - a model that cannot be loaded is a result
            results[model] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        rows = [
            ctx.corpus.index[w]
            for w in ctx.labels.works(split="train", sampling="random")
            if w in ctx.corpus.index
        ]
        results[model] = {"signal_ap": _signal_ap(ctx, "emb_desc", rows), "cv": _cv_f1(ctx)}
    return results


def local_embedding(ctx_factory, variants=local_embed.VARIANTS) -> dict:
    """Experiment 2. ``ctx_factory(variant)`` builds a context with that local input."""
    results: dict = {}
    for variant in variants:
        ctx = ctx_factory(variant)
        local = {r for r in local_embed.local_rows(ctx.corpus)}
        train = ctx.labels.works(split="train")
        random_train = ctx.labels.works(split="train", sampling="random")
        rows_random = [ctx.corpus.index[w] for w in random_train if ctx.corpus.index[w] in local]
        rows_train = [ctx.corpus.index[w] for w in train if ctx.corpus.index[w] in local]
        results[variant] = {
            "n_works_random_train": len(rows_random),
            "n_works_all_train": len(rows_train),
            "signal_ap_emb_seed": _signal_ap(ctx, "emb_seed", rows_random),
            "signal_ap_emb_desc": _signal_ap(ctx, "emb_desc", rows_random),
            "cv_local_works": _cv_f1(ctx, local),
        }
    return results


def with_config(ctx_cfg, **embedding):
    """A copy of the config with some ``embedding`` settings changed."""
    cfg = ctx_cfg.model_copy(deep=True)
    cfg.embedding = cfg.embedding.model_copy(update=embedding)
    return cfg
