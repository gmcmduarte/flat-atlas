"""Freeze: fit every variant on gold-train, run every check that needs no held-out label, and write
down the settings before the held-out set is opened (PLAN §9.6, P1-08).

Nothing here reads a held-out label. The held-out works are scored as unlabelled works (their
probabilities are in the variants' ``final`` sets) and the file written at the end records:

- the settings that decide the numbers (a hash of ``config/tagger.yaml`` without the three
  switches that adopt a result), the SHA-256 of ``gold.yaml`` and ``topics.yaml``;
- for each variant its selection, its model hash, the hash of its stored probabilities, its
  cross-validated numbers on gold-train and its label-free checks;
- the works every fit used (training, calibration, seed sets), so the opening can refuse if a
  held-out work is among them.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from flatatlas.db import write_text_atomic
from flatatlas.evaluate import checks, variants
from flatatlas.evaluate.variants import KEYS, Variant
from flatatlas.quality import CheckResult
from flatatlas.tagging import evaluate as cv
from flatatlas.tagging import noisyor, propagate, runner
from flatatlas.tagging import pairs as pairs_mod
from flatatlas.tagging import shortlist as shortlist_mod
from flatatlas.tagging.config import TaggerConfig, config_hash
from flatatlas.tagging.fusion import FusionModel
from flatatlas.tagging.pairs import KIND_GOLD_RANDOM, Pairs
from flatatlas.tagging.signals import Signals
from flatatlas.venues import load_venues

# The three settings that adopt a result are not part of what the held-out numbers depend on.
ADOPTION = {"method": True, "decision_model": {"enabled"}, "propagation": {"enabled"}}


def tuning_hash(cfg: TaggerConfig) -> str:
    """A digest of every setting except the three adoption switches (which are set *after*)."""
    return config_hash(cfg, exclude=ADOPTION)  # type: ignore[arg-type]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_path(reports: Path, run_id: str) -> Path:
    return reports / f"frozen-{run_id}.json"


def default_run_id(cfg: TaggerConfig) -> str:
    return f"p1-08-{cfg.tagger_version}-{tuning_hash(cfg)}"


# -- the checks of one variant ------------------------------------------------------------


def hard_checks(res: dict, cfg: TaggerConfig) -> dict[str, bool]:
    e = cfg.evaluation
    return {
        "anchors": res["anchors"]["rate"] >= e.anchors_min,
        "coverage": res["coverage"]["strict"] >= e.coverage_min,
        "stability": res["stability"]["unchanged"] >= e.stability_min,
        "venue_sanity": res["venue_sanity"]["rate"] >= 1.0,
    }


def leak_test(ctx: runner.Context, model: FusionModel | None, v: Variant, sels) -> dict:
    """Hide ``lex_title`` for a sample of unlabelled works: do the other signals give the tags back?

    The shortlist, the noisy-or score and the pair features are rebuilt without it."""
    cfg, dag = ctx.cfg, ctx.dag
    title = np.nan_to_num(ctx.sig.matrices["lex_title"], nan=0.0)
    eligible = [
        r
        for r in range(len(ctx.corpus))
        if ctx.corpus.work_ids[r] not in ctx.guard.labelled
        and title[r].max() >= 0.85
        and sels[r].primary is not None
    ]
    rows = checks.leak_sample(ctx.corpus.work_ids, eligible, cfg.evaluation.leak_sample, cfg.seed)
    matrices = {k: m.copy() for k, m in ctx.sig.matrices.items()}
    # 0, not NaN: a work with no title match has lex_title 0, and NaN marks silver pairs in training
    matrices["lex_title"][rows] = 0.0
    sig2 = Signals(matrices, ctx.sig.work)
    p_noisy = noisyor.noisy_or(matrices, cfg)
    cand = shortlist_mod.shortlist(sig2, p_noisy, cfg)
    closed = shortlist_mod.with_ancestors(cand, dag)
    pairs2: Pairs = pairs_mod.build_pairs(
        sig2, ctx.art, dag, ctx.corpus, ctx.labels, closed, cand, p_noisy, cfg
    )
    p = pairs2.p_noisy if v.method == "noisy_or" else model.predict(pairs2)[2]
    probs = {r: d for r, d in cv.work_probabilities(pairs2, p).items() if r in rows}
    after = checks.select_all(probs, len(ctx.corpus), dag, v.selection, cfg.selection.fallback_min)
    return checks.recovery(sels, after, rows, dag)


def run_variant_checks(
    ctx: runner.Context, v: Variant, graph: propagate.Graph, fam_agreement: dict
) -> tuple[dict, checks.SelMap]:
    cfg, dag = ctx.cfg, ctx.dag
    sels = checks.select_all(v.final, len(ctx.corpus), dag, v.selection, cfg.selection.fallback_min)
    venues = load_venues().venues
    expected = {x.acronym: list(x.expected_topics) for x in venues if x.expected_topics}
    anchors = runner.anchor_check(ctx, v.final)
    res = {
        "selection": v.selection,
        "coverage": checks.coverage(sels),
        "anchors": {
            **anchors["groups"]["all (held-out excluded)"],
            "groups": anchors["groups"],
            "misses": anchors["misses"],
        },
        "venue_sanity": checks.venue_sanity(
            sels, ctx.corpus.venues, expected, dag, cfg.evaluation.venue_top
        ),
        "citation_consistency": checks.citation_consistency(sels, graph.edges, dag),
        "coverage_by_type": checks.coverage_by_type(sels, checks.paper_type(ctx.corpus)),
    }
    return res, sels


# -- the freeze ------------------------------------------------------------------------------------


def freeze(
    ctx: runner.Context,
    ctx_seed2: runner.Context,
    *,
    run_id: str,
    reports: Path,
    log=print,
) -> dict:
    """Build everything, check it, write ``frozen-<run_id>.json`` and the stored probabilities."""
    cfg, dag = ctx.cfg, ctx.dag
    tuning_json = ctx.model_dir / "tuning.json"
    kind = (
        json.loads(tuning_json.read_text("utf-8")).get("model_kind", "lightgbm")
        if tuning_json.exists()
        else "lightgbm"
    )
    vdir = ctx.model_dir / "variants"
    log("fitting the eight variants on gold-train ...")
    built = variants.build(ctx, kind, models_dir=vdir, log=log)
    log("second seed, for the stability check ...")
    built2 = variants.build(
        ctx_seed2,
        kind,
        selections={k: v.selection for k, v in built.items()},
        dm_base={**built["fusion"].final, **built["fusion"].oof},
        log=log,
    )
    graph = propagate.load_graph(ctx.con, ctx.corpus)
    fam = checks.family_level0(ctx.sig.matrices, dag, cfg)
    agreement = checks.method_agreement(fam, dag, cfg.evaluation.agreement_flag)
    out_variants: dict[str, dict] = {}
    for key in KEYS:
        v = built[key]
        log(f"checks for {key} ...")
        res, sels = run_variant_checks(ctx, v, graph, agreement)
        sels2 = checks.select_all(
            built2[key].final, len(ctx.corpus), dag, v.selection, cfg.selection.fallback_min
        )
        res["stability"] = checks.stability(sels, sels2)
        res["coherence"] = checks.coherence(sels, ctx.corpus, dag, seed=cfg.seed)
        if key in ("noisy_or", "fusion"):
            model = FusionModel.load(vdir / "fusion.pkl") if key == "fusion" else None
            res["leak_test"] = leak_test(ctx, model, v, sels)
        res["hard"] = hard_checks(res, cfg)
        probs_file = vdir / f"{key}.probs.parquet"
        out_variants[key] = {
            "label": v.label,
            "selection": v.selection,
            "model_sha256": v.model_sha,
            "probs_file": str(probs_file),
            "probs_sha256": variants.save_probs(ctx, v.final, probs_file),
            "cv": v.cv,
            "checks": res,
        }
    train_works = sorted(
        {ctx.corpus.work_ids[r] for r in np.unique(ctx.pairs.work[ctx.pairs.label >= 0])}
    )
    calib_works = sorted(
        {
            ctx.corpus.work_ids[r]
            for r in np.unique(
                ctx.pairs.work[(ctx.pairs.label >= 0) & (ctx.pairs.kind == KIND_GOLD_RANDOM)]
            )
        }
    )
    seed_works = sorted({ctx.corpus.work_ids[r] for rows in ctx.art.seeds for r in rows})
    gold_path, topics_path = ctx.gold_path, ctx.topics_path
    frozen = {
        "run_id": run_id,
        "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tagger_version": cfg.tagger_version,
        "taxonomy_version": ctx.topics_file.taxonomy_version,
        "tuning_hash": tuning_hash(cfg),
        "config_hash": config_hash(cfg),
        "gold_sha256": sha256_file(gold_path),
        "topics_sha256": sha256_file(topics_path),
        "model_kind": kind,
        "n_works": len(ctx.corpus),
        "decision_model": ctx.notes.get("dm", {}),
        "propagation": {
            "citer_weight": cfg.propagation.citer_weight,
            "ref_weight": cfg.propagation.ref_weight,
            "noisy_or_weights": cfg.propagation.noisy_or_weights,
            "n_edges": len(graph.edges),
            "n_influential_edges": sum(1 for e in graph.edges if e[2]),
        },
        "fit_sets": {
            "training_works": train_works,
            "calibration_works": calib_works,
            "seed_works": seed_works,
            "topdown_works": ctx.labels.works(split="train"),
        },
        "method_agreement": agreement,
        "variants": out_variants,
    }
    write_text_atomic(frozen_path(reports, run_id), json.dumps(frozen, indent=1, sort_keys=True))
    return frozen


def results_for_ops(frozen: dict, cfg: TaggerConfig, adopted_key: str) -> list[CheckResult]:
    """Rows for ``ops_quality_report``: every variant's hard checks; only the adopted variant's
    failures fail the run (``passed`` of the others is recorded but reported as information)."""
    e = cfg.evaluation
    out: list[CheckResult] = []
    for key, v in frozen["variants"].items():
        c = v["checks"]
        h = c["hard"]
        rows = [
            ("anchors", c["anchors"]["rate"], e.anchors_min, h["anchors"]),
            ("coverage", c["coverage"]["strict"], e.coverage_min, h["coverage"]),
            ("stability", c["stability"]["unchanged"], e.stability_min, h["stability"]),
            ("venue_sanity", c["venue_sanity"]["rate"], 1.0, h["venue_sanity"]),
        ]
        for name, value, thr, ok in rows:
            fails_run = key == adopted_key
            out.append(
                CheckResult(
                    f"{name}[{key}]",
                    float(value),
                    thr,
                    bool(ok or not fails_run),
                    "adopted variant" if fails_run else "not adopted: reported only",
                )
            )
    return out
