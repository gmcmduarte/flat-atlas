"""Orchestration of cascade steps 1 and 2: prepare, fit, tag, explain (P1-07).

``prepare`` loads everything and computes signals, the shortlist and the pair features (artefacts
are cached by key and frozen per ``tagger_version``). ``fit`` cross-validates the models on
gold-train, tunes the selection on gold-train, and fits and saves the model. ``tag`` writes
``tag_signal`` and ``tag_work_topic``. No step touches a held-out label.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa

from flatatlas.db import replace_table, write_text_atomic
from flatatlas.settings import Settings
from flatatlas.tagging import artefacts as art_mod
from flatatlas.tagging import descriptions, evaluate, inputs, noisyor
from flatatlas.tagging import pairs as pairs_mod
from flatatlas.tagging import shortlist as shortlist_mod
from flatatlas.tagging.artefacts import Artefacts
from flatatlas.tagging.config import SIGNALS, TaggerConfig
from flatatlas.tagging.fusion import FusionModel, fit_two_stage, select_tags
from flatatlas.tagging.guard import Guard
from flatatlas.tagging.inputs import Corpus, Dag, Labels
from flatatlas.tagging.pairs import FEATURES, Pairs
from flatatlas.tagging.signals import Signals, compute_signals
from flatatlas.taxonomy import check as tcheck
from flatatlas.taxonomy import stage as tstage
from flatatlas.taxonomy.schema import TopicsFile

METHODS = ("noisy_or", "fusion")


class Missing(RuntimeError):
    """Something the tagger needs is not there; the message says what to run."""


@dataclass
class Context:
    settings: Settings
    cfg: TaggerConfig
    con: duckdb.DuckDBPyConnection
    topics_file: TopicsFile
    dag: Dag
    labels: Labels
    guard: Guard
    corpus: Corpus
    art: Artefacts
    sig: Signals
    p_noisy: np.ndarray
    candidates: np.ndarray
    closed: np.ndarray
    pairs: Pairs
    topics_path: Path
    gold_path: Path
    notes: dict = field(default_factory=dict)

    @property
    def model_dir(self) -> Path:
        return self.settings.paths.root / "models" / "tagger" / self.cfg.tagger_version


def prepare(
    settings: Settings,
    cfg: TaggerConfig,
    con: duckdb.DuckDBPyConnection,
    *,
    topics_path: Path = tcheck.TOPICS_FILE,
    gold_path: Path = tcheck.GOLD_FILE,
    desc: descriptions.DescSpace | None = None,
    use_cache: bool = True,
) -> Context:
    """Signals, shortlist and pair features for every work."""
    topics_file, dag = inputs.load_dag(topics_path)
    labels = inputs.load_labels(gold_path)
    guard = Guard(labels.gold)
    corpus = inputs.load_corpus(con)
    if cfg.embedding.local_input != "stored":
        from flatatlas.tagging import local_embed

        local_embed.apply_local_input(
            corpus, cfg.embedding.local_input, settings.paths.cache / "tagger", cfg
        )
    key = art_mod.cache_key(cfg, topics_file.taxonomy_version, topics_path, gold_path, corpus)
    if desc is not None:
        key += "-" + desc.model
    path = settings.paths.cache / "tagger" / f"artefacts-{key}.pkl"
    art: Artefacts | None = None
    if use_cache and path.exists():
        art = Artefacts.load(path)
    if art is None:
        mined = tstage.read_phrases(settings.paths)
        space = desc or descriptions.describe(
            cfg.embedding.description_model,
            dag.topics,
            corpus.parts,
            settings.paths.cache / "tagger",
            device=cfg.embedding.device,
            batch_size=cfg.embedding.batch_size,
        )
        art = art_mod.build_artefacts(topics_file, dag, corpus, labels, cfg, mined, space, key=key)
        if use_cache:
            art.save(path)
    sig = compute_signals(art, corpus, dag, labels, cfg)
    p_noisy = noisyor.noisy_or(sig.matrices, cfg)
    cand = shortlist_mod.shortlist(sig, p_noisy, cfg)
    closed = shortlist_mod.with_ancestors(cand, dag)
    pairs = pairs_mod.build_pairs(sig, art, dag, corpus, labels, closed, cand, p_noisy, cfg)
    return Context(
        settings, cfg, con, topics_file, dag, labels, guard, corpus, art, sig,
        p_noisy, cand, closed, pairs, topics_path, gold_path,
    )  # fmt: skip


# -- fit -------------------------------------------------------------------------------------------


def _round(d: dict) -> dict:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


def level_report(
    probs: dict[int, dict[int, float]],
    gold: dict[int, set[int]],
    dag: Dag,
    cfg: TaggerConfig,
    selection: dict,
) -> dict:
    rows = sorted(gold)
    pred = evaluate.predict_sets(
        probs,
        rows,
        dag,
        threshold=selection["threshold"],
        max_topics=selection["max_topics"],
        fallback_min=cfg.selection.fallback_min,
    )
    out = {"n_works": len(rows), "selection": _round(selection)}
    for level in (0, 1):
        out[f"level{level}"] = _round(evaluate.score_level(pred, gold, dag, level).__dict__)
    out["unsure_share"] = round(
        evaluate.unsure_share(probs, rows, dag, cfg.selection.unsure_band), 4
    )
    out["unsure_by_band"] = {
        f"{lo}-{hi}": round(evaluate.unsure_share(probs, rows, dag, (lo, hi)), 4)
        for lo, hi in ((0.2, 0.6), (0.25, 0.55), (0.3, 0.5), (0.35, 0.45))
    }
    return out


def cross_validated_report(ctx: Context, kinds: tuple[str, ...] = ("logistic", "lightgbm")) -> dict:
    """Cross-validated numbers on gold-train for methods (a) and (c), per sampling subset."""
    cfg, dag = ctx.cfg, ctx.dag
    train = ctx.labels.works(split="train")
    random_train = ctx.labels.works(split="train", sampling="random")
    gold_random = evaluate.gold_sets(ctx.labels, ctx.corpus, dag, random_train)
    gold_all = evaluate.gold_sets(ctx.labels, ctx.corpus, dag, train)
    report: dict = {"methods": {}}

    methods: dict[str, dict[int, dict[int, float]]] = {
        "noisy_or": evaluate.work_probabilities(ctx.pairs, ctx.pairs.p_noisy)
    }
    for kind in kinds:
        methods[kind] = evaluate.cross_validate(
            ctx.pairs, ctx.corpus, ctx.labels, ctx.guard, cfg, kind, eval_works=train
        )
    for name, probs in methods.items():
        tuned = evaluate.tune_selection(probs, gold_random, dag, cfg)
        default = {"threshold": cfg.selection.threshold, "max_topics": cfg.selection.max_topics}
        report["methods"][name] = {
            "tuned": _round(tuned),
            "random_train": level_report(probs, gold_random, dag, cfg, tuned),
            "all_train": level_report(probs, gold_all, dag, cfg, tuned),
            "random_train_at_defaults": level_report(probs, gold_random, dag, cfg, default),
        }
    return report


def choose_kind(report: dict, cfg: TaggerConfig, kinds=("logistic", "lightgbm")) -> str:
    """The simpler model (logistic) unless LightGBM is better by ``complex_margin`` (mean F1)."""
    scores = {k: report["methods"][k]["tuned"]["f1_mean"] for k in kinds if k in report["methods"]}
    if "lightgbm" in scores and "logistic" in scores:
        if scores["lightgbm"] >= scores["logistic"] + cfg.fusion.complex_margin:
            return "lightgbm"
        return "logistic"
    return next(iter(scores))


def fit(ctx: Context, *, kinds: tuple[str, ...] = ("logistic", "lightgbm")) -> dict:
    """Cross-validate, choose, fit the final model on all gold-train + silver, and save it."""
    report = cross_validated_report(ctx, kinds)
    kind = choose_kind(report, ctx.cfg, kinds)
    model, info = fit_two_stage(ctx.pairs, ctx.corpus, ctx.guard, ctx.cfg, kind)
    model.selection = {
        "threshold": report["methods"][kind]["tuned"]["threshold"],
        "max_topics": report["methods"][kind]["tuned"]["max_topics"],
    }
    digest = model.save(ctx.model_dir / "fusion.pkl")
    tuning = {
        "tagger_version": ctx.cfg.tagger_version,
        "taxonomy_version": ctx.topics_file.taxonomy_version,
        "artefacts_key": ctx.art.key,
        "model_kind": kind,
        "model_sha256": digest,
        "fusion_selection": model.selection,
        "noisy_or_selection": {
            "threshold": report["methods"]["noisy_or"]["tuned"]["threshold"],
            "max_topics": report["methods"]["noisy_or"]["tuned"]["max_topics"],
        },
        "n_pairs": info["n_pairs"],
        "n_gold_pairs": info["n_gold"],
        "n_silver_pairs": info["n_silver"],
        "n_calibration_pairs": info["n_calibration"],
        "cv": report,
    }
    write_text_atomic(ctx.model_dir / "tuning.json", json.dumps(tuning, indent=2, sort_keys=True))
    return tuning


def load_model(ctx: Context) -> tuple[FusionModel, dict]:
    path, tuning_path = ctx.model_dir / "fusion.pkl", ctx.model_dir / "tuning.json"
    if not path.exists() or not tuning_path.exists():
        raise Missing(f"no fitted model in {ctx.model_dir}; run `flatatlas tag fit` first")
    tuning = json.loads(tuning_path.read_text(encoding="utf-8"))
    if tuning["artefacts_key"] != ctx.art.key:
        raise Missing(
            "the saved model was fitted on other artefacts "
            f"({tuning['artefacts_key']} != {ctx.art.key}); run `flatatlas tag fit`"
        )
    return FusionModel.load(path), tuning


# -- tagging ---------------------------------------------------------------------------------------

_S = pa.string()
_SIGNAL_STRUCT = pa.struct([("name", _S), ("score", pa.float32())])
_MODEL_STRUCT = pa.struct([("name", _S), ("sha256", _S)])
PROVENANCE = pa.struct(
    [
        ("method", _S),
        ("signals", pa.list_(_SIGNAL_STRUCT)),
        ("models", pa.list_(_MODEL_STRUCT)),
        ("tagger_version", _S),
        ("taxonomy_version", pa.int32()),
        ("flags", pa.list_(_S)),
    ]
)
TAG_WORK_TOPIC = pa.schema(
    [
        ("work_id", _S),
        ("topic_id", _S),
        ("confidence", pa.float32()),
        ("rank", pa.int16()),
        ("is_primary", pa.bool_()),
        ("provenance", PROVENANCE),
        ("derived", pa.bool_()),
    ]
)
_FLOAT = pa.float32()
TAG_SIGNAL = pa.schema(
    [
        ("work_id", _S),
        ("topic_id", _S),
        *[(name, _FLOAT) for name in FEATURES],
        ("shortlisted", pa.bool_()),
        ("p_noisy_or", _FLOAT),
        ("p_stage_a", _FLOAT),
        ("parent_p", _FLOAT),
        ("p_fusion", _FLOAT),
        ("tagger_version", _S),
    ]
)


@dataclass
class TagResult:
    method: str
    n_works: int
    n_tagged: int
    untagged: list[str]
    n_rows: int
    low_confidence: int
    unsure_share: float
    model_sha256: str | None
    seconds: float = 0.0


def _signal_rows(ctx: Context, rows: set[int], p_a, parent, p_f) -> list[dict]:
    pr = ctx.pairs
    out = []
    for i in np.flatnonzero(np.isin(pr.work, np.fromiter(rows, dtype=np.int64))):
        row = {
            "work_id": ctx.corpus.work_ids[pr.work[i]],
            "topic_id": ctx.dag.ids[pr.topic[i]],
            "shortlisted": bool(pr.candidate[i]),
            "p_noisy_or": float(pr.p_noisy[i]),
            "p_stage_a": None if p_a is None else float(p_a[i]),
            "parent_p": None if parent is None or np.isnan(parent[i]) else float(parent[i]),
            "p_fusion": None if p_f is None else float(p_f[i]),
            "tagger_version": ctx.cfg.tagger_version,
        }
        for j, name in enumerate(FEATURES):
            v = float(pr.X[i, j])
            row[name] = None if np.isnan(v) else v
        out.append(row)
    return out


def _signals_of_pair(ctx: Context, i: int) -> list[dict]:
    return [
        {"name": name, "score": float(ctx.pairs.X[i, FEATURES.index(name)])}
        for name in SIGNALS
        if not np.isnan(ctx.pairs.X[i, FEATURES.index(name)])
    ]


def tag(ctx: Context, method: str, *, limit: int | None = None) -> TagResult:
    """Tag the works (all, or the first ``limit`` by ID); write the two tag tables."""
    import time

    t0 = time.perf_counter()
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    cfg, dag, pairs = ctx.cfg, ctx.dag, ctx.pairs
    rows = sorted(set(pairs.work.tolist()))
    # works with no pair at all (empty text) are untagged too
    all_rows = list(range(len(ctx.corpus)))
    chosen = all_rows[:limit] if limit else all_rows

    model = None
    tuning: dict = {}
    p_a = parent = p_f = None
    try:
        model, tuning = load_model(ctx)
        p_a, parent, p_f = model.predict(pairs)
    except Missing:
        if method == "fusion":
            raise
    if method == "fusion":
        assert model is not None
        probs = evaluate.work_probabilities(pairs, p_f)
        selection = tuning["fusion_selection"]
        models = [{"name": f"fusion-{model.kind}", "sha256": tuning["model_sha256"]}]
    else:
        probs = evaluate.work_probabilities(pairs, pairs.p_noisy)
        selection = tuning.get(
            "noisy_or_selection",
            {"threshold": cfg.selection.threshold, "max_topics": cfg.selection.max_topics},
        )
        models = []

    index = {
        (int(r), int(t)): i for i, (r, t) in enumerate(zip(pairs.work, pairs.topic, strict=True))
    }
    out_rows: list[dict] = []
    untagged: list[str] = []
    n_low = 0
    for r in chosen:
        work_id = ctx.corpus.work_ids[r]
        sel = select_tags(
            probs.get(r, {}),
            dag,
            threshold=selection["threshold"],
            max_topics=selection["max_topics"],
            fallback_min=cfg.selection.fallback_min,
        )
        if sel.untagged:
            untagged.append(work_id)
            continue
        n_low += int(sel.low_confidence)
        ordered = sorted(sel.rows, key=lambda x: (x[2], -x[1], x[0]))
        for rank, (t, conf, derived) in enumerate(ordered, start=1):
            i = index.get((r, t))
            out_rows.append(
                {
                    "work_id": work_id,
                    "topic_id": dag.ids[t],
                    "confidence": float(conf),
                    "rank": rank,
                    "is_primary": (t == sel.primary) and not derived,
                    "provenance": {
                        "method": method,
                        "signals": _signals_of_pair(ctx, i) if i is not None else [],
                        "models": models,
                        "tagger_version": cfg.tagger_version,
                        "taxonomy_version": ctx.topics_file.taxonomy_version,
                        "flags": ["low_confidence"] if sel.low_confidence else [],
                    },
                    "derived": derived,
                }
            )
    paths = ctx.settings.paths
    con = ctx.con
    new = pa.Table.from_pylist(out_rows, schema=TAG_WORK_TOPIC)
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "tag_work_topic" in have:
        old = con.sql(
            "SELECT * FROM tag_work_topic WHERE provenance.method <> $m", params={"m": method}
        ).to_arrow_table()
        if old.num_rows:
            new = pa.concat_tables([old.cast(TAG_WORK_TOPIC), new])
    replace_table(con, "tag_work_topic", new, paths.warehouse / "core" / "tag_work_topic.parquet")
    sig_rows = _signal_rows(ctx, set(chosen), p_a, parent, p_f)
    replace_table(
        con,
        "tag_signal",
        pa.Table.from_pylist(sig_rows, schema=TAG_SIGNAL),
        paths.warehouse / "local" / "tag_signal.parquet",
    )
    report = paths.reports / f"tag-untagged-{method}.txt"
    write_text_atomic(report, "\n".join(untagged) + ("\n" if untagged else ""))
    rows_chosen = [r for r in chosen if r in set(rows)]
    unsure = evaluate.unsure_share(probs, rows_chosen, dag, cfg.selection.unsure_band)
    return TagResult(
        method=method,
        n_works=len(chosen),
        n_tagged=len(chosen) - len(untagged),
        untagged=untagged,
        n_rows=len(out_rows),
        low_confidence=n_low,
        unsure_share=unsure,
        model_sha256=tuning.get("model_sha256") if method == "fusion" else None,
        seconds=time.perf_counter() - t0,
    )


# -- explain ---------------------------------------------------------------------------------------


def explain(ctx: Context, work_id: str, *, top: int = 6) -> str:
    """Why a work got its tags: text, signals per candidate topic, hits, model contributions."""
    from flatatlas.tagging.signals import lexical_row

    if work_id not in ctx.corpus.index:
        raise Missing(f"unknown work {work_id}")
    r = ctx.corpus.index[work_id]
    part = ctx.corpus.parts[r]
    dag, pairs, cfg = ctx.dag, ctx.pairs, ctx.cfg
    lines = [f"{work_id}  {part.title}", f"  {part.venue} {part.year}"]
    wf = {k: v[r] for k, v in ctx.sig.work.items()}
    lines.append(
        "  context: " + ", ".join(f"{k}={'nan' if np.isnan(v) else int(v)}" for k, v in wf.items())
    )
    if work_id in ctx.labels.by_work:
        lab = ctx.labels.by_work[work_id]
        lines.append(
            f"  labelled set: {ctx.labels.split[work_id]}/{ctx.labels.sampling[work_id]}  "
            f"(for the reader; never a tag): {', '.join(sorted(lab))}"
        )
    model = None
    try:
        model, tuning = load_model(ctx)
        _p_a, parent, p_f = model.predict(pairs)
    except Missing:
        parent = p_f = None
        tuning = {}
    idx = np.flatnonzero(pairs.work == r)
    prob = p_f if p_f is not None else pairs.p_noisy
    idx = sorted(idx, key=lambda i: -prob[i])
    lines.append(f"  {len(idx)} pairs scored (candidates plus ancestors); top {top}:")
    title_s, abs_s, refs_s = lexical_row(
        ctx.art.include, ctx.art.exclude, part, cfg.signals.lex_abstract_scale
    )
    for i in idx[:top]:
        t = int(pairs.topic[i])
        sigs = []
        for name in SIGNALS:
            v = pairs.X[i, FEATURES.index(name)]
            sigs.append(f"{name}={'-' if np.isnan(v) else f'{v:.2f}'}")
        mark = "cand" if pairs.candidate[i] else "anc "
        fused = f"fusion {p_f[i]:.2f}  " if p_f is not None else ""
        lines.append(
            f"  - {dag.ids[t]} [L{dag.level[t]}, {mark}]  {fused}noisy-or {pairs.p_noisy[i]:.2f}"
        )
        lines.append("      " + "  ".join(sigs))
        hits = []
        for label, scores in (("title", title_s), ("abstract", abs_s), ("refs", refs_s)):
            if scores and t in scores:
                hits.append(f"{label} {scores[t]:.2f}")
        if hits:
            lines.append("      lexical: " + ", ".join(hits))
        if model is not None:
            XB = np.hstack([pairs.X[i], parent[i] if not np.isnan(parent[i]) else np.nan])
            contrib = model.stage_b.contributions(XB.astype(np.float32), list(model.columns))
            lines.append(
                "      largest contributions: " + ", ".join(f"{n} {v:+.2f}" for n, v in contrib[:5])
            )
            if not np.isnan(parent[i]):
                lines.append(f"      best parent probability (stage A): {parent[i]:.2f}")
    if model is not None:
        probs = evaluate.work_probabilities(pairs, p_f)
        sel = select_tags(
            probs.get(r, {}),
            dag,
            threshold=tuning["fusion_selection"]["threshold"],
            max_topics=tuning["fusion_selection"]["max_topics"],
            fallback_min=cfg.selection.fallback_min,
        )
        if sel.untagged:
            lines.append("  selection: untagged")
        else:
            tags = ", ".join(
                f"{dag.ids[t]}{'*' if t == sel.primary else ''}{'(derived)' if d else ''} {c:.2f}"
                for t, c, d in sel.rows
            )
            lines.append(
                f"  selection (fusion, threshold {tuning['fusion_selection']['threshold']}): {tags}"
            )
    return "\n".join(lines)


def count_kinds(pairs: Pairs) -> dict:
    return dict(Counter(int(k) for k in pairs.kind))


def anchor_check(ctx: Context) -> dict:
    """The anchor papers in the corpus: is the expected topic among the 3 most probable?

    Groups: ``not in gold`` (clean), ``gold-train`` (the model saw their labels: in-sample).
    Held-out anchors are skipped.
    """
    from flatatlas.taxonomy import anchors as tanchors

    anchors_file = tcheck.load_anchors()
    corpus_ids = tanchors.load_corpus(ctx.con)
    model, _tuning = load_model(ctx)
    _pa, _parent, p_f = model.predict(ctx.pairs)
    probs = evaluate.work_probabilities(ctx.pairs, p_f)
    groups: dict[str, list[bool]] = {"not in gold": [], "gold-train (in-sample)": []}
    misses: list[str] = []
    for anchor in anchors_file.anchors:
        work = corpus_ids.work_of(anchor)
        if work is None or work not in ctx.corpus.index:
            continue
        if anchor.topic not in ctx.dag.index:
            continue
        if work in ctx.guard.heldout:
            continue
        r = ctx.corpus.index[work]
        ranked = sorted(probs.get(r, {}).items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        top = [ctx.dag.ids[t] for t, _p in ranked]
        hit = anchor.topic in top
        group = "gold-train (in-sample)" if work in ctx.guard.labelled else "not in gold"
        groups[group].append(hit)
        if not hit:
            misses.append(f"{anchor.id} ({group}): expected {anchor.topic}, got {', '.join(top)}")
    out = {}
    for name, hits in groups.items():
        out[name] = {"n": len(hits), "hit": sum(hits), "rate": sum(hits) / max(len(hits), 1)}
    both = [h for hits in groups.values() for h in hits]
    out["all (held-out excluded)"] = {
        "n": len(both),
        "hit": sum(both),
        "rate": sum(both) / max(len(both), 1),
    }
    return {"groups": out, "misses": misses}
