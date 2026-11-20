"""The eight methods of the comparison, each fitted on gold-train and scored for every work.

(a) noisy-or, (b) top-down, (c) learned fusion without the decision model, (c) with it; each
without and with propagation (pass 2). A variant keeps two sets of probabilities:

- ``oof``: out of fold, for the gold-train works only. This is what tuning reads (the selection
  threshold and maximum number of topics, the propagation settings). No held-out work is in it.
- ``final``: from the model fitted on all gold-train (plus silver), for every work. The held-out
  works are scored here, as unlabelled works; no label of theirs reaches any fit (``Guard``).

Pass-1 topic vectors for propagation come from the variant's own method (noisy-or, top-down), and
from the base fusion model for the two fusion variants (so the decision model enters in pass 2
next to the neighbours, not inside the neighbours' vectors). For gold-train works the pass-1 vector
is out of fold.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from flatatlas.db import write_parquet_atomic
from flatatlas.tagging import evaluate as cv
from flatatlas.tagging import noisyor, propagate, topdown
from flatatlas.tagging.config import PropagationConfig
from flatatlas.tagging.decide import stage as dstage
from flatatlas.tagging.fusion import fit_model
from flatatlas.tagging.runner import Context, level_report

KEYS = (
    "noisy_or",
    "noisy_or+prop",
    "topdown",
    "topdown+prop",
    "fusion",
    "fusion+prop",
    "fusion+dm",
    "fusion+dm+prop",
)
LABELS = {
    "noisy_or": "(a) noisy-or",
    "noisy_or+prop": "(a) noisy-or + propagation",
    "topdown": "(b) top-down",
    "topdown+prop": "(b) top-down + propagation",
    "fusion": "(c) fusion",
    "fusion+prop": "(c) fusion + propagation",
    "fusion+dm": "(c) fusion + decision model",
    "fusion+dm+prop": "(c) fusion + decision model + propagation",
}
# Each more complex option against its simpler neighbour (PLAN §9.6). (b) is a baseline: it is
# compared with (a) and with (c), never adopted over them by this ladder.
LADDER = {
    "noisy_or+prop": "noisy_or",
    "topdown+prop": "topdown",
    "fusion": "noisy_or",
    "fusion+prop": "fusion",
    "fusion+dm": "fusion",
    "fusion+dm+prop": "fusion+dm",
}
BASELINE_VS = {"topdown": ("noisy_or", "fusion")}

Probs = dict[int, dict[int, float]]


@dataclass
class Variant:
    key: str
    oof: Probs
    final: Probs
    selection: dict
    cv: dict
    model_sha: str | None = None
    notes: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return LABELS[self.key]

    @property
    def method(self) -> str:
        return self.key.split("+")[0]

    @property
    def dm(self) -> bool:
        return "+dm" in self.key

    @property
    def prop(self) -> bool:
        return self.key.endswith("+prop")


def key_of(method: str, dm: bool, prop: bool) -> str:
    """The variant a configuration ships: ``method``, with the decision model, with propagation."""
    base = method + ("+dm" if dm and method == "fusion" else "")
    return base + ("+prop" if prop else "")


# -- probabilities on disk ------------------------------------------------------------------------

_SCHEMA = pa.schema([("work_id", pa.string()), ("topic_id", pa.string()), ("p", pa.float32())])


def save_probs(ctx: Context, probs: Probs, path: Path) -> str:
    """Write ``probs`` (every scored pair) and return the SHA-256 of the file."""
    import hashlib

    rows = [
        {"work_id": ctx.corpus.work_ids[r], "topic_id": ctx.dag.ids[t], "p": p}
        for r, row in sorted(probs.items())
        for t, p in sorted(row.items())
    ]
    write_parquet_atomic(pa.Table.from_pylist(rows, schema=_SCHEMA), path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_probs(path: Path, work_index: dict[str, int], topic_index: dict[str, int]) -> Probs:
    out: Probs = {}
    for row in pq.read_table(path).to_pylist():
        r, t = work_index.get(row["work_id"]), topic_index.get(row["topic_id"])
        if r is not None and t is not None:
            out.setdefault(r, {})[t] = float(row["p"])
    return out


# -- building ------------------------------------------------------------------------------------


def _pairs_probs(ctx: Context, p: np.ndarray) -> Probs:
    return cv.work_probabilities(ctx.pairs, p)


def _tuned(ctx: Context, oof: Probs, selection: dict | None) -> tuple[dict, dict]:
    """``(selection, cv numbers)``: tuned on random-train out-of-fold probabilities unless given."""
    dag, cfg = ctx.dag, ctx.cfg
    random_train = ctx.labels.works(split="train", sampling="random")
    train = ctx.labels.works(split="train")
    gold_random = cv.gold_sets(ctx.labels, ctx.corpus, dag, random_train)
    gold_all = cv.gold_sets(ctx.labels, ctx.corpus, dag, train)
    tuned = selection or cv.tune_selection(oof, gold_random, dag, cfg)
    sel = {"threshold": tuned["threshold"], "max_topics": tuned["max_topics"]}
    report = {
        "random_train": level_report(oof, gold_random, dag, cfg, sel),
        "all_train": level_report(oof, gold_all, dag, cfg, sel),
    }
    return sel, report


def _fusion_cell(
    ctx: Context, kind: str, *, use_dm: bool, use_prop: bool, selection: dict | None
) -> tuple[Variant, object]:
    train = ctx.labels.works(split="train")
    oof = cv.cross_validate(
        ctx.pairs, ctx.corpus, ctx.labels, ctx.guard, ctx.cfg, kind,
        eval_works=train, use_dm=use_dm, use_prop=use_prop,
    )  # fmt: skip
    model, info = fit_model(
        ctx.pairs, ctx.corpus, ctx.guard, ctx.cfg, kind, use_dm=use_dm, use_prop=use_prop
    )
    _pa, _parent, p = model.predict(ctx.pairs)
    final = _pairs_probs(ctx, p)
    sel, report = _tuned(ctx, oof, selection)
    key = key_of("fusion", use_dm, use_prop)
    model.selection = sel
    return Variant(
        key, oof, final, sel, report, notes={"n_calibration": info["n_calibration"]}
    ), model


def build(
    ctx: Context,
    kind: str = "lightgbm",
    *,
    selections: dict[str, dict] | None = None,
    models_dir: Path | None = None,
    dm_base: Probs | None = None,
    log=print,
) -> dict[str, Variant]:
    """Fit and score all eight variants. ``selections`` fixes the selection of a variant (stability
    re-runs use the first run's); ``models_dir`` is where the fitted models are saved, if anywhere.
    ``dm_base`` fixes the base probabilities that decide which works the decision model answered
    (a re-run under another seed must use the first run's, or it would look for answers that were
    never asked for).
    """
    selections = selections or {}
    cfg, dag, pairs = ctx.cfg, ctx.dag, ctx.pairs
    train = ctx.labels.works(split="train")
    graph = propagate.load_graph(ctx.con, ctx.corpus)
    out: dict[str, Variant] = {}

    def save_model(key: str, model) -> str | None:
        if models_dir is None:
            return None
        models_dir.mkdir(parents=True, exist_ok=True)
        if hasattr(model, "save"):
            return model.save(models_dir / f"{key}.pkl")
        import hashlib

        blob = pickle.dumps(model, protocol=pickle.HIGHEST_PROTOCOL)
        (models_dir / f"{key}.pkl").write_bytes(blob)
        return hashlib.sha256(blob).hexdigest()

    # pass 1: (a), (c) base, (b)
    propagate.clear(pairs)
    p1_noisy = _pairs_probs(ctx, pairs.p_noisy)
    sel, report = _tuned(ctx, p1_noisy, selections.get("noisy_or"))
    out["noisy_or"] = Variant("noisy_or", p1_noisy, p1_noisy, sel, report)
    log("  noisy_or done")

    base, base_model = _fusion_cell(ctx, kind, use_dm=False, use_prop=False,
                                    selection=selections.get("fusion"))  # fmt: skip
    base.model_sha = save_model("fusion", base_model)
    out["fusion"] = base
    log("  fusion done")

    X0 = topdown.feature_matrix(ctx.corpus, dag)
    td_oof, td_model = _topdown_cell(ctx, X0, use_prop=False)
    td_final = topdown.predict_all(td_model, X0, dag)
    sel, report = _tuned(ctx, td_oof, selections.get("topdown"))
    out["topdown"] = Variant(
        "topdown", td_oof, td_final, sel, report, save_model("topdown", td_model)
    )
    log("  topdown done")

    by_work = {**base.final, **base.oof}  # the base probabilities the decision model was asked on
    dstage.activate(ctx, by_work=dm_base if dm_base is not None else by_work)
    dm, dm_model = _fusion_cell(ctx, kind, use_dm=True, use_prop=False,
                                selection=selections.get("fusion+dm"))  # fmt: skip
    dm.model_sha = save_model("fusion+dm", dm_model)
    out["fusion+dm"] = dm
    log("  fusion+dm done")

    # pass 2
    n_topics = dag.n
    pcfg: PropagationConfig = cfg.propagation
    mats_f = propagate.matrices(by_work, graph, n_topics, pcfg)
    mats_n = propagate.matrices(p1_noisy, graph, n_topics, pcfg)
    mats_t = propagate.matrices({**td_final, **td_oof}, graph, n_topics, pcfg)

    extra = {k: v.astype(np.float32) for k, v in mats_n.items()}
    p2 = noisyor.noisy_or(ctx.sig.matrices, cfg, extra=extra)[pairs.work, pairs.topic]
    n2 = _pairs_probs(ctx, p2)
    sel, report = _tuned(ctx, n2, selections.get("noisy_or+prop"))
    out["noisy_or+prop"] = Variant("noisy_or+prop", n2, n2, sel, report)

    propagate.attach(pairs, mats_f)
    for use_dm in (False, True):
        v, m = _fusion_cell(ctx, kind, use_dm=use_dm, use_prop=True,
                            selection=selections.get(key_of("fusion", use_dm, True)))  # fmt: skip
        v.model_sha = save_model(v.key, m)
        out[v.key] = v
        log(f"  {v.key} done")
    propagate.clear(pairs)

    X1 = topdown.feature_matrix(ctx.corpus, dag, mats_t)
    td2_oof, td2_model = _topdown_cell(ctx, X1, use_prop=True)
    td2_final = topdown.predict_all(td2_model, X1, dag)
    sel, report = _tuned(ctx, td2_oof, selections.get("topdown+prop"))
    out["topdown+prop"] = Variant(
        "topdown+prop", td2_oof, td2_final, sel, report, save_model("topdown+prop", td2_model)
    )
    log("  pass 2 done")
    ctx.notes["train_works"] = train
    return {k: out[k] for k in KEYS}


def _topdown_cell(ctx: Context, X: np.ndarray, *, use_prop: bool):
    train = ctx.labels.works(split="train")
    oof = topdown.cross_validate(
        ctx.corpus, ctx.dag, ctx.labels, ctx.guard, ctx.cfg, X, train, use_prop=use_prop
    )
    model = topdown.fit(
        ctx.corpus, ctx.dag, ctx.labels, ctx.guard, ctx.cfg, X, train, use_prop=use_prop
    )
    return oof, model
