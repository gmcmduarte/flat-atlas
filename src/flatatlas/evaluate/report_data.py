"""What the HTML report lists per topic and per work, built from the stored probabilities."""

from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb

from flatatlas.evaluate import checks
from flatatlas.evaluate.report import WorkLink, link
from flatatlas.evaluate.variants import load_probs
from flatatlas.tagging.config import TaggerConfig
from flatatlas.tagging.inputs import Corpus, Dag


def work_links(con: duckdb.DuckDBPyConnection, corpus: Corpus) -> dict[int, WorkLink]:
    out: dict[int, WorkLink] = {}
    rows = con.execute(
        "SELECT w.work_id, w.title, w.year, v.doi, v.dblp_key FROM core_work w "
        "LEFT JOIN core_version v ON v.version_id = w.primary_version_id"
    ).fetchall()
    for work_id, title, year, doi, dblp in rows:
        r = corpus.index.get(work_id)
        if r is not None:
            out[r] = WorkLink(title or "", int(year) if year else None, doi, dblp)
    return out


def topic_rows(frozen: dict, adopted: str, sels: checks.SelMap, dag: Dag, cfg: TaggerConfig):
    """One row per topic that has works: size, mean confidence, agreement, coherence, flag."""
    coh = frozen["variants"][adopted]["checks"]["coherence"]
    agree = frozen["method_agreement"]["per_topic"]
    members: dict[int, list[float]] = {}
    for s in sels.values():
        for t, p, _d in s.rows:
            members.setdefault(t, []).append(p)
    rows = []
    for t, confs in sorted(members.items(), key=lambda kv: dag.ids[kv[0]]):
        tid = dag.ids[t]
        c = coh["topics"].get(tid, {})
        a = agree.get(tid)
        cos = c.get("cosine")
        flag = (a is not None and a < cfg.evaluation.agreement_flag) or (
            cos is not None
            and cos == cos
            and cos < coh["baseline_cosine"] + cfg.evaluation.coherence_margin
        )
        rows.append(
            {
                "id": tid,
                "level": int(dag.level[t]),
                "n": len(confs),
                "mean_conf": sum(confs) / len(confs),
                "agreement": a,
                "npmi": c.get("npmi"),
                "cosine": cos,
                "flag": bool(flag),
            }
        )
    return rows


def spot_lists(
    corpus: Corpus,
    dag: Dag,
    sels: checks.SelMap,
    probs_a: dict[int, dict[int, float]],
    probs_b: dict[int, dict[int, float]],
    links: dict[int, WorkLink],
    cfg: TaggerConfig,
    other_label: str,
) -> dict[str, dict[str, list[str]]]:
    """Per topic: the random, lowest-confidence and strongest-disagreement works, as HTML items."""
    n = cfg.evaluation.spot_n
    entries: dict[int, list[tuple[int, float, bool]]] = {}
    for r, s in sels.items():
        for t, p, d in s.rows:
            entries.setdefault(t, []).append((r, p, d))
    disagree: dict[int, list[tuple[float, int, float, float]]] = {}
    for r, d in probs_a.items():
        other = probs_b.get(r, {})
        for t, pa in d.items():
            pb = other.get(t, 0.0)
            if max(pa, pb) >= 0.35:
                disagree.setdefault(t, []).append((abs(pa - pb), r, pa, pb))

    def item(r: int, extra: str) -> str:
        w = links.get(r)
        return link(w, extra) if w else f"<li>{corpus.work_ids[r]} {extra}</li>"

    def order(r: int, t: int) -> str:
        return hashlib.sha256(f"spot:{cfg.seed}:{corpus.work_ids[r]}:{t}".encode()).hexdigest()

    out: dict[str, dict[str, list[str]]] = {}
    for t in sorted(entries, key=lambda x: dag.ids[x]):
        rows = entries[t]
        rand = sorted(rows, key=lambda e: order(e[0], t))[:n]
        low = sorted(rows, key=lambda e: (e[1], corpus.work_ids[e[0]]))[:n]
        dis = sorted(disagree.get(t, []), key=lambda e: (-e[0], corpus.work_ids[e[1]]))[:n]
        out[dag.ids[t]] = {
            "10 random": [item(r, f"confidence {p:.2f}") for r, p, _d in rand],
            "10 lowest confidence": [item(r, f"confidence {p:.2f}") for r, p, _d in low],
            f"10 strongest disagreement with {other_label}": [
                item(r, f"adopted {pa:.2f} vs {pb:.2f}") for _d, r, pa, pb in dis
            ],
        }
    return out


def load_variant_probs(frozen: dict, key: str, corpus: Corpus, dag: Dag):
    return load_probs(Path(frozen["variants"][key]["probs_file"]), corpus.index, dag.index)
