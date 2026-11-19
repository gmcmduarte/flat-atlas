"""Cascade step 3 glue: the base probabilities, the unsure works, the run, the features.

``tag fit`` saves, next to the shipped model, the **base** model (no ``dm_*`` features) and
``base_probs.parquet``: the base probability of every shortlisted pair, out of fold for gold-train
works and from the final base model for every other work. The unsure works are chosen from those
numbers (``select``), ``tag decide`` asks the model about them, and ``activate`` puts the cached
answers into the pair features before the fusion model reads them.

Held-out works are asked about like any other work (inference only); no fit sees their labels.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pyarrow as pa

from flatatlas.db import write_parquet_atomic
from flatatlas.tagging.decide import questions as q
from flatatlas.tagging.decide.cache import DecisionCache, ModelInfo
from flatatlas.tagging.decide.features import attach
from flatatlas.tagging.decide.run import (
    RunReport,
    WorkTask,
    level0,
    order_effect,
    run_decisions,
    topic_of,
)
from flatatlas.tagging.decide.scorer import (
    LlamaScorer,
    MissingLlmExtra,
    Scorer,
    file_sha256,
    peak_memory_mb,
)
from flatatlas.tagging.decide.select import band_hits, disagreement_rows

if TYPE_CHECKING:
    from flatatlas.tagging.runner import Context

log = logging.getLogger(__name__)

BASE_MODEL = "fusion-base.pkl"
BASE_PROBS = "base_probs.parquet"
_PROBS = pa.schema(
    [
        ("work_id", pa.string()),
        ("topic_id", pa.string()),
        ("p", pa.float32()),
        ("source", pa.string()),
    ]
)


class MissingDecisionInput(RuntimeError):
    """The base model, the model file or the runtime is not there; the message says what to run."""


# -- the base probabilities ---------------------------------------------------------------------


def save_base_probs(
    ctx: Context, final: dict[int, dict[int, float]], oof: dict[int, dict[int, float]]
) -> Path:
    """Write the base probabilities: ``oof`` for the works it covers, ``final`` for the rest."""
    rows = []
    for r, probs in sorted(final.items()):
        source, use = ("oof", oof[r]) if r in oof else ("final", probs)
        for t, p in sorted(use.items()):
            rows.append(
                {
                    "work_id": ctx.corpus.work_ids[r],
                    "topic_id": ctx.dag.ids[t],
                    "p": p,
                    "source": source,
                }
            )
    return write_parquet_atomic(
        pa.Table.from_pylist(rows, schema=_PROBS), ctx.model_dir / BASE_PROBS
    )


def read_base_probs(ctx: Context) -> dict[int, dict[int, float]]:
    import pyarrow.parquet as pq

    path = ctx.model_dir / BASE_PROBS
    if not path.exists():
        raise MissingDecisionInput(
            f"no base probabilities in {ctx.model_dir}; run `flatatlas tag fit`"
        )
    out: dict[int, dict[int, float]] = {}
    for row in pq.read_table(path).to_pylist():
        r, t = ctx.corpus.index.get(row["work_id"]), ctx.dag.index.get(row["topic_id"])
        if r is not None and t is not None:
            out.setdefault(r, {})[t] = float(row["p"])
    return out


def unsure_rows(ctx: Context, by_work: dict[int, dict[int, float]]) -> set[int]:
    """The corpus rows the decision model is asked about (band, plus disagreement if enabled)."""
    rows = band_hits(by_work, ctx.dag, tuple(ctx.cfg.selection.unsure_band))
    if ctx.cfg.decision_model.select.disagreement:
        rows |= disagreement_rows(ctx.sig.matrices, ctx.dag, ctx.cfg)
    return rows


# -- model and cache ----------------------------------------------------------------------------


def model_path(ctx: Context) -> Path:
    return ctx.settings.paths.root / "models" / ctx.cfg.decision_model.model_file


def model_sha(ctx: Context) -> str:
    path = model_path(ctx)
    if not path.exists():
        raise MissingDecisionInput(f"model file not found: {path} (see docs/notes/sources.md)")
    return file_sha256(path)


def cache_path(ctx: Context) -> Path:
    return ctx.settings.paths.warehouse / "local" / "local_decision.parquet"


def load_scorer(ctx: Context) -> LlamaScorer:
    dm = ctx.cfg.decision_model
    try:
        return LlamaScorer(model_path(ctx), n_ctx=dm.n_ctx, n_threads=dm.n_threads)
    except MissingLlmExtra as exc:
        raise MissingDecisionInput(str(exc)) from exc


def model_info(ctx: Context, runtime: str) -> ModelInfo:
    dm = ctx.cfg.decision_model
    return ModelInfo(
        file=model_path(ctx).name,
        sha256=model_sha(ctx),
        quantisation=dm.quantisation,
        runtime=runtime,
        prompt_version=q.PROMPT_VERSION,
    )


# -- features -----------------------------------------------------------------------------------


def activate(ctx: Context, by_work: dict[int, dict[int, float]] | None = None) -> dict:
    """Put the cached answers of the unsure works into ``ctx.pairs`` (raw ``dm_*``); once."""
    if "dm" in ctx.notes:
        return ctx.notes["dm"]
    dm = ctx.cfg.decision_model
    by_work = by_work if by_work is not None else read_base_probs(ctx)
    rows = unsure_rows(ctx, by_work)
    cache = DecisionCache.load(ctx.con)
    answers = cache.answers(
        model_sha(ctx),
        q.PROMPT_VERSION,
        n_orders=dm.option_orders,
        l0_topics=level0(ctx.dag),
        topic_index=ctx.dag.index,
    )
    active = {ctx.corpus.work_ids[r] for r in rows}
    counts = attach(ctx.pairs, ctx.dag, ctx.corpus.work_ids, answers, active)
    info = {
        "unsure_works": len(active),
        "works_with_answers": counts["works"],
        "pairs_l0": counts["pairs_l0"],
        "pairs_child": counts["pairs_child"],
        "band": list(ctx.cfg.selection.unsure_band),
        "disagreement": dm.select.disagreement,
        "unsure_works_missing_answers": sorted(
            w for w in active if w not in answers or answers[w].l0 is None
        )[:20],
    }
    ctx.notes["dm"] = info
    log.info("decision model: %s", info)
    return info


# -- the run ------------------------------------------------------------------------------------


def make_tasks(
    ctx: Context, rows: Sequence[int], by_work: dict[int, dict[int, float]]
) -> list[WorkTask]:
    shortlisted: dict[int, set[int]] = {}
    pr = ctx.pairs
    for r, t, cand in zip(pr.work.tolist(), pr.topic.tolist(), pr.candidate.tolist(), strict=True):
        if cand:
            shortlisted.setdefault(r, set()).add(t)
    return [
        WorkTask(
            work_id=ctx.corpus.work_ids[r],
            text=ctx.corpus.parts[r].text,
            base_p=by_work.get(r, {}),
            shortlisted=shortlisted.get(r, set()),
        )
        for r in rows
    ]


def choose_rows(
    ctx: Context,
    by_work: dict[int, dict[int, float]],
    *,
    all_works: bool,
    limit: int | None,
    works: Sequence[str] | None = None,
) -> list[int]:
    if works:
        unknown = [w for w in works if w not in ctx.corpus.index]
        if unknown:
            raise MissingDecisionInput(f"unknown work(s): {', '.join(unknown)}")
        rows = sorted(ctx.corpus.index[w] for w in works)
    elif all_works:
        rows = list(range(len(ctx.corpus)))
    else:
        rows = sorted(unsure_rows(ctx, by_work))
    rows.sort(key=lambda r: ctx.corpus.work_ids[r])
    return rows[:limit] if limit else rows


def decide(
    ctx: Context,
    *,
    limit: int | None = None,
    all_works: bool = False,
    orders: int | None = None,
    bench: bool = False,
    works: Sequence[str] | None = None,
    scorer: Scorer | None = None,
) -> tuple[RunReport, dict]:
    """Ask the model about the unsure works (or ``all_works``, or the named ``works``).

    ``bench`` keeps the answers in memory only (nothing is read from or written to the cache), so
    timings are not helped by an earlier run. Returns the report and a dictionary of numbers.
    """
    by_work = read_base_probs(ctx)
    rows = choose_rows(ctx, by_work, all_works=all_works, limit=limit, works=works)
    tasks = make_tasks(ctx, rows, by_work)
    scorer = scorer or load_scorer(ctx)
    info = model_info(ctx, getattr(scorer, "runtime", "fake"))
    cache = DecisionCache() if bench else DecisionCache.load(ctx.con)

    def flush() -> None:
        cache.save(ctx.con, cache_path(ctx))

    report = run_decisions(
        tasks,
        dag=ctx.dag,
        scorer=scorer,
        cache=cache,
        info=info,
        cfg=ctx.cfg.decision_model,
        orders=orders,
        flush=None if bench else flush,
    )
    n = max(len(tasks), 1)
    numbers = {
        "works": len(tasks),
        "asked": {"choice": report.l0_asked, "yes_no": report.child_asked},
        "from_cache": {"choice": report.l0_cached, "yes_no": report.child_cached},
        "seconds": round(report.seconds, 1),
        "seconds_per_work": round(report.seconds / n, 2),
        "phase_seconds_per_work": {k: round(v / n, 2) for k, v in report.phase_seconds.items()},
        "tokens_per_work": {
            k: {
                "prompt": round(s.prompt_tokens / n, 1),
                "evaluated": round(s.evaluated_tokens / n, 1),
                "calls_per_work": round(s.calls / n, 2),
            }
            for k, s in report.phase_stats.items()
        },
        "peak_memory_mb": round(peak_memory_mb()),
        "order_effect": order_effect(report, len(level0(ctx.dag))),
        "model": {
            "file": info.file,
            "sha256": info.sha256,
            "quantisation": info.quantisation,
            "runtime": info.runtime,
            "prompt_version": info.prompt_version,
        },
    }
    return report, numbers


def explain_report(ctx: Context, report: RunReport, orders: int | None = None) -> str:
    """The questions asked and the probabilities, work by work (local; may show abstracts)."""
    dag = ctx.dag
    l0 = level0(dag)
    lines: list[str] = []
    n_orders = orders or ctx.cfg.decision_model.option_orders
    l0_topics = [topic_of(dag, t) for t in l0]
    order = q.option_orders(len(l0), n_orders)[0]
    for work_id, res in report.results.items():
        r = ctx.corpus.index[work_id]
        part = ctx.corpus.parts[r]
        lines.append(f"{work_id}  {part.title}  ({part.venue} {part.year})")
        lines.append(
            f"  choice question over {len(l0)} level-0 topics, "
            f"{len(res.l0_by_order)} option order(s):"
        )
        for k, probs in enumerate(res.l0_by_order, start=1):
            top = np.argsort(-probs)[:3]
            lines.append(
                f"    order {k}: " + ", ".join(f"{dag.ids[l0[i]]} {probs[i]:.2f}" for i in top)
            )
        if res.l0 is not None:
            top = np.argsort(-res.l0)[:5]
            lines.append(
                "    average: " + ", ".join(f"{dag.ids[l0[i]]} {res.l0[i]:.2f}" for i in top)
            )
        lines.append(f"  yes/no questions ({len(res.child)}):")
        for t, p in sorted(res.child.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {dag.ids[t]}: p(yes) {p:.2f}")
        lines.append("  the choice prompt (order 1):")
        lines.extend(
            "    | " + ln for ln in q.choice_prompt(part.text, l0_topics, order).splitlines()
        )
        if res.child:
            t0 = next(iter(res.child))
            lines.append(f"  the yes/no prompt for {dag.ids[t0]}:")
            lines.extend(
                "    | " + ln for ln in q.yesno_prompt(part.text, topic_of(dag, t0)).splitlines()
            )
        lines.append("")
    return "\n".join(lines)
