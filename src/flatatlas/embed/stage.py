"""The ``embed`` stage (PLAN §5, stage 5): S2 vectors first, local SPECTER2 for the rest (P1-03).

``parse s2`` has already put every Semantic Scholar vector into ``local_embedding``. This stage
computes a vector locally for each paper that has none and keeps exactly one row per paper
(``store.write_source`` enforces it). ``compare`` embeds papers that *do* have an S2 vector with the
local model and reports how close the two are, which is the check that local vectors can stand in
for S2's.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import duckdb
import numpy as np

from flatatlas.abstracts import best_abstracts
from flatatlas.embed import store
from flatatlas.embed.specter2 import (
    DEFAULT_SEP,
    MODEL_LABEL,
    EmbedStats,
    Encoder,
    VectorCache,
    embed_texts,
    format_input,
)
from flatatlas.settings import Paths

SALT = "p1-03-embed"


@dataclass(frozen=True)
class PaperText:
    dblp_key: str
    title: str
    abstract: str | None
    abstract_source: str | None


def load_paper_texts(
    con: duckdb.DuckDBPyConnection, venue_ids: list[str] | None = None
) -> list[PaperText]:
    """Every DBLP paper (front matter left out) with its best abstract, in key order."""
    where, args = "NOT is_front_matter", []
    if venue_ids:
        where += f" AND venue_id IN ({', '.join('?' * len(venue_ids))})"
        args = list(venue_ids)
    rows = con.execute(
        f"SELECT dblp_key, title FROM stg_dblp_paper WHERE {where} ORDER BY dblp_key", args
    ).fetchall()
    abstracts = best_abstracts(con)
    out = []
    for key, title in rows:
        source, text = abstracts.get(key, (None, None))
        out.append(PaperText(key, title or "", text, source))
    return out


def sample_order(key: str) -> str:
    """A stable pseudo-random order, so a small run is a mixed sample."""
    return hashlib.sha1(f"{key}|{SALT}".encode()).hexdigest()  # noqa: S324 - not security


def papers_without_s2_vector(
    con: duckdb.DuckDBPyConnection, papers: list[PaperText]
) -> list[PaperText]:
    have = {r["dblp_key"] for r in store.read_rows(con, source="s2")}
    return [p for p in papers if p.dblp_key not in have]


@dataclass
class EmbedResult:
    stats: EmbedStats
    wanted: int  # papers that needed a local vector
    done: int  # of those, embedded in this run
    kinds: dict[str, int]
    coverage: dict[str, Any]


def run_embed(
    con: duckdb.DuckDBPyConnection,
    paths: Paths,
    encoder: Encoder,
    papers: list[PaperText],
    *,
    limit: int | None = None,
    batch_size: int = 32,
    on_progress: Callable[[str], None] | None = None,
) -> EmbedResult:
    """Embed the papers without an S2 vector (at most ``limit`` of them) and store the rows."""
    missing = papers_without_s2_vector(con, papers)
    todo = sorted(missing, key=lambda p: sample_order(p.dblp_key)) if limit else list(missing)
    if limit:
        todo = todo[:limit]
    sep = getattr(encoder, "sep", DEFAULT_SEP)
    inputs = [format_input(p.title, p.abstract, sep) for p in todo]
    vectors, stats = embed_texts(
        [text for text, _kind in inputs],
        encoder,
        batch_size=batch_size,
        cache=VectorCache(paths.cache / "embed" / "specter2"),
        on_progress=on_progress,
    )
    new_rows = {
        p.dblp_key: {
            "dblp_key": p.dblp_key,
            "model": MODEL_LABEL,
            "source": "local",
            "s2_corpus_id": None,
            "input_kind": kind,
            "abstract_source": p.abstract_source if kind == "title+abstract" else None,
            "vector": vec.tolist(),
        }
        for p, (_text, kind), vec in zip(todo, inputs, vectors, strict=True)
    }
    # Earlier local rows stay (a --limit run adds to them); an S2 row for the same paper wins.
    rows = {r["dblp_key"]: r for r in store.read_rows(con, source="local")}
    rows.update(new_rows)
    store.write_source(con, paths, "local", list(rows.values()))
    kinds: dict[str, int] = {}
    for _text, kind in inputs:
        kinds[kind] = kinds.get(kind, 0) + 1
    return EmbedResult(
        stats=stats,
        wanted=len(missing),
        done=len(todo),
        kinds=kinds,
        coverage=store.coverage(con, [p.dblp_key for p in papers]),
    )


# -- local versus Semantic Scholar -------------------------------------------------------------


@dataclass
class Comparison:
    n: int
    rows: list[dict[str, Any]]  # per paper: key, kind, cosine (and cosine_sep for title-only)
    stats: EmbedStats
    device: str


def _summary(values: list[float]) -> dict[str, float]:
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return {"n": 0}
    return {
        "n": int(arr.size),
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "min": float(arr.min()),
        "p05": float(np.percentile(arr, 5)),
        "share_ge_0.9": float((arr >= 0.9).mean()),
    }


def summarise(comparison: Comparison) -> dict[str, dict[str, float]]:
    out = {"all": _summary([r["cosine"] for r in comparison.rows])}
    for kind in ("title+abstract", "title"):
        out[kind] = _summary([r["cosine"] for r in comparison.rows if r["kind"] == kind])
    out["title (with trailing [SEP], model-card style)"] = _summary(
        [r["cosine_sep"] for r in comparison.rows if r.get("cosine_sep") is not None]
    )
    return out


def compare_with_s2(
    con: duckdb.DuckDBPyConnection,
    encoder: Encoder,
    papers: list[PaperText],
    *,
    n: int = 50,
    batch_size: int = 32,
    device: str = "cpu",
    on_progress: Callable[[str], None] | None = None,
) -> Comparison:
    """Embed ``n`` papers that have an S2 vector with the local model; cosine against S2's.

    Papers without an abstract are embedded twice, as ``title`` and as ``title[SEP]``, to see
    which form Semantic Scholar's vectors resemble. The sample mixes papers with and without an
    abstract (at most half of it without) so both cases are measured.
    """
    s2 = {r["dblp_key"]: r["vector"] for r in store.read_rows(con, source="s2")}
    pool = sorted((p for p in papers if p.dblp_key in s2), key=lambda p: sample_order(p.dblp_key))
    with_abs = [p for p in pool if p.abstract]
    without = [p for p in pool if not p.abstract]
    half = n // 2
    pick_without = without[: max(half, n - len(with_abs))]
    chosen = (with_abs[: n - len(pick_without)] + pick_without)[:n]
    sep = getattr(encoder, "sep", DEFAULT_SEP)

    texts, kinds = (
        zip(*(format_input(p.title, p.abstract, sep) for p in chosen), strict=True)
        if chosen
        else ((), ())
    )
    vectors, stats = embed_texts(
        list(texts), encoder, batch_size=batch_size, on_progress=on_progress
    )
    reference = (
        store.as_matrix([s2[p.dblp_key] for p in chosen]) if chosen else np.zeros((0, store.DIM))
    )
    cos = store.cosine_pairs(vectors, reference) if chosen else np.zeros(0)

    sep_idx = [i for i, k in enumerate(kinds) if k == "title"]
    cos_sep: dict[int, float] = {}
    if sep_idx:
        alt, _ = embed_texts(
            [format_input(chosen[i].title, None, sep, sep_when_empty=True)[0] for i in sep_idx],
            encoder,
            batch_size=batch_size,
        )
        alt_cos = store.cosine_pairs(alt, reference[sep_idx])
        cos_sep = {i: float(c) for i, c in zip(sep_idx, alt_cos, strict=True)}
    rows = [
        {
            "dblp_key": p.dblp_key,
            "kind": kinds[i],
            "abstract_source": p.abstract_source,
            "cosine": float(cos[i]),
            "cosine_sep": cos_sep.get(i),
        }
        for i, p in enumerate(chosen)
    ]
    return Comparison(n=len(chosen), rows=rows, stats=stats, device=device)


def render_comparison(comparison: Comparison, *, profile: str) -> str:
    summary = summarise(comparison)
    lines = [
        f"# Local SPECTER2 versus Semantic Scholar vectors: {profile}",
        "",
        "Generated by `flatatlas embed compare`. Regenerate it; do not edit.",
        "",
        f"- Model: `{MODEL_LABEL}`, device `{comparison.device}`.",
        f"- Sample: {comparison.n} papers that have an S2 vector (hash-ordered, mixed with and "
        "without abstract).",
        f"- Local throughput: {comparison.stats.per_second:.1f} texts/s "
        f"({comparison.stats.computed} texts in {comparison.stats.seconds:.1f} s of encoder time).",
        "",
        "| Group | n | mean cosine | median | min | 5th percentile | share >= 0.9 |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, s in summary.items():
        if not s.get("n"):
            lines.append(f"| {name} | 0 | | | | | |")
            continue
        lines.append(
            f"| {name} | {s['n']} | {s['mean']:.4f} | {s['median']:.4f} | {s['min']:.4f} | "
            f"{s['p05']:.4f} | {s['share_ge_0.9']:.0%} |"
        )
    worst = sorted(comparison.rows, key=lambda r: r["cosine"])[:5]
    lines += ["", "Lowest five:", ""]
    lines += [
        f"- `{r['dblp_key']}` ({r['kind']}, abstract from {r['abstract_source'] or 'none'}): "
        f"{r['cosine']:.4f}"
        for r in worst
    ]
    return "\n".join(lines) + "\n"
