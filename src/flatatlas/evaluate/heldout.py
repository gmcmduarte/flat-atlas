"""The one-time opening of the held-out labelled set (PLAN §9.6, D-61).

``verify`` refuses unless the frozen file still matches the files and settings it was made from and
no held-out work appears in any set a fit used. ``open_heldout`` scores all eight variants in one
go, writes the numbers and a lock file. A second opening is refused unless ``again`` is given, and
then every number is labelled optimistic: the settings were free to change in between.

Scores are agreement with the labelled set, Claude's reading of the works (D-91, D-93).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from flatatlas.db import write_text_atomic
from flatatlas.evaluate import checks, metrics
from flatatlas.evaluate.freeze import sha256_file, tuning_hash
from flatatlas.evaluate.variants import BASELINE_VS, KEYS, LADDER, load_probs
from flatatlas.tagging import evaluate as cv
from flatatlas.tagging.config import TaggerConfig
from flatatlas.tagging.inputs import Corpus, Dag, Labels


class HeldoutRefused(RuntimeError):
    """The held-out set must not be opened (or must not be opened again)."""


def lock_path(reports: Path) -> Path:
    return reports / "heldout-opened.json"


def verify(
    frozen: dict,
    cfg: TaggerConfig,
    heldout_works: set[str],
    *,
    gold_path: Path,
    topics_path: Path,
) -> None:
    """Refuse when the frozen record is stale or a held-out work was used to fit anything."""
    problems = []
    if frozen["tuning_hash"] != tuning_hash(cfg):
        problems.append(
            "config/tagger.yaml changed after the freeze (apart from the adoption switches)"
        )
    if frozen["gold_sha256"] != sha256_file(gold_path):
        problems.append("taxonomy/gold.yaml changed after the freeze")
    if frozen["topics_sha256"] != sha256_file(topics_path):
        problems.append("taxonomy/topics.yaml changed after the freeze")
    for name, works in frozen["fit_sets"].items():
        bad = sorted(set(works) & heldout_works)
        if bad:
            problems.append(
                f"{len(bad)} held-out work(s) in the {name} set ({', '.join(bad[:3])}...)"
            )
    for key, v in frozen["variants"].items():
        path = Path(v["probs_file"])
        if not path.exists() or sha256_file(path) != v["probs_sha256"]:
            problems.append(f"the stored probabilities of {key} are missing or changed")
    if problems:
        raise HeldoutRefused("; ".join(problems))


def no_worse(complex_checks: dict, simple_checks: dict) -> dict:
    """Does the more complex variant keep every hard check?

    A hard check *gets worse* when the simpler method meets its threshold and the more complex one
    does not (PLAN §9.6: the hard checks are the ones with a hard threshold). The values are kept
    so the report can show a drop that stays above the threshold; read in the other way (any fall
    counts) no learned model could ever beat noisy-or, whose stability is exactly 1 (D-100).
    """
    pairs = {
        "anchors": (complex_checks["anchors"]["rate"], simple_checks["anchors"]["rate"]),
        "coverage": (complex_checks["coverage"]["strict"], simple_checks["coverage"]["strict"]),
        "stability": (
            complex_checks["stability"]["unchanged"],
            simple_checks["stability"]["unchanged"],
        ),
        "venue_sanity": (
            complex_checks["venue_sanity"]["rate"],
            simple_checks["venue_sanity"]["rate"],
        ),
    }
    out: dict = {}
    for name, (c, s) in pairs.items():
        worse = bool(simple_checks["hard"][name] and not complex_checks["hard"][name])
        out[name] = {"complex": c, "simple": s, "worse": worse}
    out["any_worse"] = any(v["worse"] for v in out.values() if isinstance(v, dict))
    return out


def decide(frozen: dict, diffs: dict[str, dict]) -> dict:
    """Walk the ladder: adopt a more complex option only if its paired interval excludes zero on
    the mean of the level 0 and level 1 F1 (and is positive) and no hard check got worse
    (``no_worse``: a check that the simpler method passes and the complex one fails)."""
    rungs = {}
    for key, simpler in LADDER.items():
        d = diffs[key]["mean_f"]
        hard = no_worse(frozen["variants"][key]["checks"], frozen["variants"][simpler]["checks"])
        rungs[key] = {
            "against": simpler,
            "diff": float(d.value),
            "lo": float(d.lo),
            "hi": float(d.hi),
            "excludes_zero": bool(metrics.excludes_zero(d)),
            "better": bool(d.value > 0),
            "hard": hard,
            "adopt": bool(metrics.excludes_zero(d) and d.value > 0 and not hard["any_worse"]),
        }
    method = "noisy_or"
    if rungs["fusion"]["adopt"]:
        method = "fusion"
        if rungs["fusion+dm"]["adopt"]:
            method = "fusion+dm"
    prop = bool(rungs[f"{method}+prop"]["adopt"])
    return {
        "rungs": rungs,
        "adopted": method + ("+prop" if prop else ""),
        "method": method,
        "decision_model": method == "fusion+dm",
        "propagation": prop,
    }


def open_heldout(
    frozen: dict,
    cfg: TaggerConfig,
    corpus: Corpus,
    dag: Dag,
    labels: Labels,
    reports: Path,
    *,
    again: bool = False,
    gold_path: Path,
    topics_path: Path,
) -> dict:
    guard_heldout = set(labels.works(split="heldout"))
    verify(frozen, cfg, guard_heldout, gold_path=gold_path, topics_path=topics_path)
    lock = lock_path(reports)
    if lock.exists() and not again:
        opened = json.loads(lock.read_text("utf-8"))
        raise HeldoutRefused(
            f"the held-out set was opened on {opened['opened']} for run {opened['run_id']}; "
            "a second opening is optimistic (settings may have changed in between). "
            "Use --again to see the numbers anyway, labelled as such."
        )
    held = sorted(w for w in guard_heldout if w in corpus.index)
    rows = [corpus.index[w] for w in held]
    gold = cv.gold_sets(labels, corpus, dag, held)
    ev = cfg.evaluation
    counts: dict[str, tuple[metrics.Counts, metrics.Counts]] = {}
    calibration: dict[str, list] = {}
    selections = {}
    for key in KEYS:
        v = frozen["variants"][key]
        probs = load_probs(Path(v["probs_file"]), corpus.index, dag.index)
        sel = v["selection"]
        selections[key] = sel
        pred = cv.predict_sets(
            probs,
            rows,
            dag,
            threshold=sel["threshold"],
            max_topics=sel["max_topics"],
            fallback_min=cfg.selection.fallback_min,
        )
        counts[key] = tuple(metrics.work_counts(pred, gold, rows, dag, lvl) for lvl in (0, 1))
        p, y = [], []
        for r in rows:
            for t, pr in probs.get(r, {}).items():
                if dag.level[t] <= 1:
                    p.append(pr)
                    y.append(int(t in gold[r]))
        calibration[key] = metrics.calibration_curve(np.array(p), np.array(y), ev.calibration_bins)
    boot = metrics.resamples(len(rows), ev.bootstrap_n, ev.bootstrap_seed)
    est = metrics.bootstrap(counts, boot, ev.interval)
    diffs = {
        k: metrics.paired_difference(counts[k], counts[s], boot, ev.interval)
        for k, s in LADDER.items()
    }
    for k, targets in BASELINE_VS.items():
        for t in targets:
            diffs[f"{k} vs {t}"] = metrics.paired_difference(
                counts[k], counts[t], boot, ev.interval
            )
    decision = decide(frozen, diffs)
    types = checks.paper_type(corpus)
    by_type: dict[str, dict] = {}
    for kind, labs in types.items():
        groups: dict[str, list[int]] = {}
        for i, r in enumerate(rows):
            groups.setdefault(str(labs[r]), []).append(i)
        by_type[kind] = {
            g: {
                "n": len(idx),
                **{
                    key: float(
                        metrics.metric_values(
                            *counts[key],
                            np.array(idx),
                            (
                                metrics.macro_topics(counts[key][0]),
                                metrics.macro_topics(counts[key][1]),
                            ),
                        )["mean_f"]
                    )
                    for key in KEYS
                },
            }
            for g, idx in sorted(groups.items())
        }
    result = {
        "run_id": frozen["run_id"],
        "opened": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "optimistic": bool(again),
        "n_works": len(rows),
        "bootstrap": {"n": ev.bootstrap_n, "seed": ev.bootstrap_seed, "interval": ev.interval},
        "selections": selections,
        "estimates": {k: {m: [e.value, e.lo, e.hi] for m, e in d.items()} for k, d in est.items()},
        "differences": {
            k: {m: [e.value, e.lo, e.hi] for m, e in d.items()} for k, d in diffs.items()
        },
        "decision": decision,
        "calibration": calibration,
        "by_type": by_type,
        "n_gold_labels": {
            "level0": int(counts["fusion"][0].tp.sum() + counts["fusion"][0].fn.sum()),
            "level1": int(counts["fusion"][1].tp.sum() + counts["fusion"][1].fn.sum()),
        },
    }
    write_text_atomic(
        reports / f"heldout-{frozen['run_id']}{'-again' if again else ''}.json",
        json.dumps(result, indent=1, sort_keys=True),
    )
    if not again:
        write_text_atomic(
            lock,
            json.dumps({"run_id": frozen["run_id"], "opened": result["opened"]}, indent=1),
        )
    return result
