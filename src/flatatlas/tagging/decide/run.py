"""Ask the decision model about a list of works, cache every answer, resume after an interruption.

For each work: the choice question over the level-0 topics in ``option_orders`` fixed orders
(averaged), then yes/no questions for the children of the most probable level-0 topics and for
shortlisted candidates, at most ``max_child_questions``. The choice questions run order by order
over all works, because the option list of one order is the same for every work and the runtime
keeps its cache; the yes/no questions run work by work, because they share the paper text.

Every answer is looked up in the cache first. A hit costs no model call, so a second run (or a run
after a crash) only asks what is missing.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from flatatlas.tagging.config import DecisionModelConfig
from flatatlas.tagging.decide import questions as q
from flatatlas.tagging.decide.cache import L0, DecisionCache, ModelInfo, make_key
from flatatlas.tagging.decide.scorer import Scorer, ScorerStats
from flatatlas.tagging.decide.select import child_questions
from flatatlas.tagging.inputs import Dag

log = logging.getLogger(__name__)


@dataclass
class WorkTask:
    """What the run needs to know about one work."""

    work_id: str
    text: str  # the composite text (local only)
    base_p: dict[int, float]  # base fusion probability by DAG topic index
    shortlisted: set[int]


@dataclass
class WorkResult:
    l0: np.ndarray | None = None  # averaged over the orders, by level-0 topic
    l0_by_order: list[np.ndarray] = field(default_factory=list)
    child: dict[int, float] = field(default_factory=dict)  # DAG topic index -> p(yes)


@dataclass
class RunReport:
    works: int = 0
    l0_asked: int = 0
    l0_cached: int = 0
    child_asked: int = 0
    child_cached: int = 0
    seconds: float = 0.0
    phase_seconds: dict[str, float] = field(default_factory=dict)
    phase_stats: dict[str, ScorerStats] = field(default_factory=dict)
    results: dict[str, WorkResult] = field(default_factory=dict)

    @property
    def asked(self) -> int:
        return self.l0_asked + self.child_asked


def _stats(scorer: Scorer) -> ScorerStats:
    s = getattr(scorer, "stats", None)
    return s.snapshot() if s is not None else ScorerStats()


def level0(dag: Dag) -> list[int]:
    return [t for t in range(dag.n) if dag.level[t] == 0]


def topic_of(dag: Dag, t: int) -> q.Topic:
    e = dag.topics[t]
    return q.Topic(e.id, e.name, e.description)


def run_decisions(
    tasks: Sequence[WorkTask],
    *,
    dag: Dag,
    scorer: Scorer,
    cache: DecisionCache,
    info: ModelInfo,
    cfg: DecisionModelConfig,
    orders: int | None = None,
    flush: Callable[[], None] | None = None,
) -> RunReport:
    """Run both phases over ``tasks``; ``flush`` is called every ``cfg.flush_every`` works."""
    n_orders = orders or cfg.option_orders
    l0 = level0(dag)
    l0_topics = [topic_of(dag, t) for t in l0]
    letters = q.choice_options(len(l0))
    order_list = q.option_orders(len(l0), n_orders)
    report = RunReport(works=len(tasks))
    t_start = time.perf_counter()
    for task in tasks:
        report.results[task.work_id] = WorkResult()

    def maybe_flush(i: int) -> None:
        if flush is not None and (i + 1) % cfg.flush_every == 0:
            flush()

    # phase A: the choice question, order by order
    for k, order in enumerate(order_list):
        name = f"choice-order-{k + 1}"
        before, t0 = _stats(scorer), time.perf_counter()
        for i, task in enumerate(tasks):
            prompt = q.choice_prompt(task.text, l0_topics, order)
            sha = q.prompt_hash(prompt)
            key = make_key(task.work_id, L0, k, info.sha256, info.prompt_version)
            probs = cache.get(key, sha)
            if probs is None:
                by_position = scorer.score(prompt, letters)
                probs = list(q.by_topic(order, by_position))
                cache.put(key, sha, probs, info)
                report.l0_asked += 1
            else:
                report.l0_cached += 1
            report.results[task.work_id].l0_by_order.append(np.asarray(probs, dtype=float))
            maybe_flush(i)
            _progress(log, name, i + 1, len(tasks), t0)
        report.phase_seconds[name] = time.perf_counter() - t0
        report.phase_stats[name] = _stats(scorer).since(before)
        if flush is not None:
            flush()
    for task in tasks:
        res = report.results[task.work_id]
        res.l0 = q.average(res.l0_by_order)

    # phase B: the yes/no questions, work by work
    before, t0 = _stats(scorer), time.perf_counter()
    for i, task in enumerate(tasks):
        res = report.results[task.work_id]
        assert res.l0 is not None
        probs_l0 = {t: float(p) for t, p in zip(l0, res.l0, strict=True)}
        for t in child_questions(
            probs_l0,
            task.base_p,
            task.shortlisted,
            dag,
            top_l0=cfg.top_l0,
            max_level=cfg.child_max_level,
            cap=cfg.max_child_questions,
        ):
            topic = topic_of(dag, t)
            prompt = q.yesno_prompt(task.text, topic)
            sha = q.prompt_hash(prompt)
            key = make_key(task.work_id, topic.id, 0, info.sha256, info.prompt_version)
            probs = cache.get(key, sha)
            if probs is None:
                p = scorer.score(prompt, q.YESNO_OPTIONS)
                probs = [float(p[0]), float(p[1])]
                cache.put(key, sha, probs, info)
                report.child_asked += 1
            else:
                report.child_cached += 1
            res.child[t] = float(probs[0])
        maybe_flush(i)
        _progress(log, "yes-no", i + 1, len(tasks), t0)
    report.phase_seconds["yes-no"] = time.perf_counter() - t0
    report.phase_stats["yes-no"] = _stats(scorer).since(before)
    if flush is not None:
        flush()
    report.seconds = time.perf_counter() - t_start
    return report


def _progress(logger: logging.Logger, phase: str, done: int, total: int, t0: float) -> None:
    if done % 25 and done != total:
        return
    elapsed = max(time.perf_counter() - t0, 1e-9)
    rate = done / elapsed * 60
    eta = (total - done) / (done / elapsed) if done else 0.0
    logger.info(
        "%s: %d/%d works, %.1f works/min, about %.0f min left", phase, done, total, rate, eta / 60
    )


def order_effect(report: RunReport, n_topics: int) -> dict:
    """How much the answer moves with the option order (needs two or more orders)."""
    shifts, same = [], 0
    n = 0
    for res in report.results.values():
        if len(res.l0_by_order) < 2 or res.l0 is None:
            continue
        top = int(np.argmax(res.l0))
        per = [float(p[top]) for p in res.l0_by_order]
        shifts.append(max(per) - min(per))
        same += len({int(np.argmax(p)) for p in res.l0_by_order}) == 1
        n += 1
    if not n:
        return {}
    return {
        "works": n,
        "top_probability_shift_mean": round(float(np.mean(shifts)), 4),
        "top_probability_shift_max": round(float(np.max(shifts)), 4),
        "same_top_topic_in_all_orders": round(same / n, 4),
    }
