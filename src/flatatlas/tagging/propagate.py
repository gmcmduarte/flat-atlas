"""Pass 2: propagation over the citation and co-authorship graphs (PLAN §9.3, §9.4, D-25).

Two signals, each a ``(works, topics)`` matrix built from **pass-1 topic vectors** (a probability
per work and topic from a pass-1 method):

- ``prop_cite``: weighted mean of the vectors of a work's references (weight ``ref_weight``) and of
  its in-corpus citers (``citer_weight``, lower: references describe a paper better than its citers
  do), each edge times ``influential_boost`` when Semantic Scholar marks the citation influential
  (``core_citation.is_influential`` is null on the pilot, so the boost has no effect there).
- ``prop_author``: for each author of the work, the mean vector of the author's *other* works
  within ``author_window`` years of the work; then the mean over the authors. The work itself is
  never included.

A work with no usable neighbour gets NaN, not zero. **One iteration only**: pass 2 reads pass-1
vectors and nothing reads pass-2 vectors, so runs stay deterministic and incremental (D-25).

Pass-1 vectors for gold-train works must be out of fold (``decide.stage.read_base_probs`` already
is), so that a training work's own label does not come back to it through a neighbour's in-sample
score. Held-out works enter only as label-free neighbours.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import numpy as np

from flatatlas.tagging.config import PropagationConfig
from flatatlas.tagging.inputs import Corpus
from flatatlas.tagging.pairs import FEATURES, PROP_FEATURES, Pairs


@dataclass
class Graph:
    """What propagation reads, as corpus rows."""

    n: int
    edges: list[tuple[int, int, bool]]  # (citing row, cited row, influential)
    authors: list[list[int]]  # author indexes per work row
    years: np.ndarray  # publication year per row (0 where unknown)


def build_graph(
    edges: list[tuple[int, int, bool]], authors: list[list[int]], years: np.ndarray
) -> Graph:
    return Graph(len(authors), edges, authors, np.asarray(years))


def load_graph(con: duckdb.DuckDBPyConnection, corpus: Corpus) -> Graph:
    """The in-corpus citation edges, the authors of each work's primary version and its year."""
    index = corpus.index
    edges = []
    for citing, cited, infl in con.execute(
        "SELECT citing_work_id, cited_work_id, is_influential FROM core_citation"
    ).fetchall():
        a, b = index.get(citing), index.get(cited)
        if a is not None and b is not None and a != b:
            edges.append((a, b, bool(infl)))
    author_ids: dict[str, int] = {}
    authors: list[list[int]] = [[] for _ in range(len(corpus))]
    for work_id, author_id in con.execute(
        "SELECT w.work_id, a.author_id FROM core_work w "
        "JOIN core_authorship a ON a.version_id = w.primary_version_id "
        "ORDER BY w.work_id, a.position"
    ).fetchall():
        r = index.get(work_id)
        if r is None:
            continue
        k = author_ids.setdefault(author_id, len(author_ids))
        if k not in authors[r]:
            authors[r].append(k)
    years = np.zeros(len(corpus), dtype=np.int64)
    for work_id, year in con.execute("SELECT work_id, year FROM core_work").fetchall():
        r = index.get(work_id)
        if r is not None and year is not None:
            years[r] = int(year)
    return Graph(len(corpus), edges, authors, years)


def vectors_from_probs(
    probs: dict[int, dict[int, float]], n_works: int, n_topics: int
) -> tuple[np.ndarray, np.ndarray]:
    """``(P, usable)``: a dense pass-1 matrix (zero where a topic was not scored) and the rows
    that have any pass-1 probability at all (a work with no pair has no vector to lend)."""
    P = np.zeros((n_works, n_topics), dtype=np.float64)
    usable = np.zeros(n_works, dtype=bool)
    for r, row in probs.items():
        for t, p in row.items():
            P[r, t] = p
        if row:
            usable[r] = True
    return P, usable


def prop_cite(
    P: np.ndarray, usable: np.ndarray, graph: Graph, cfg: PropagationConfig
) -> np.ndarray:
    """Weighted mean of the pass-1 vectors of references and citers; NaN without neighbours."""
    num = np.zeros_like(P, dtype=np.float64)
    den = np.zeros(P.shape[0], dtype=np.float64)
    for citing, cited, influential in graph.edges:
        if citing == cited:  # a work never lends its vector to itself
            continue
        boost = cfg.influential_boost if influential else 1.0
        if usable[cited]:  # the cited work is a reference of the citing one
            w = cfg.ref_weight * boost
            num[citing] += w * P[cited]
            den[citing] += w
        if usable[citing]:  # the citing work is a citer of the cited one
            w = cfg.citer_weight * boost
            num[cited] += w * P[citing]
            den[cited] += w
    out = np.full(P.shape, np.nan, dtype=np.float64)
    has = den > 0
    out[has] = num[has] / den[has, None]
    return out


def prop_author(
    P: np.ndarray, usable: np.ndarray, graph: Graph, cfg: PropagationConfig
) -> np.ndarray:
    """Mean over a work's authors of the mean vector of their other works within the window."""
    works_of: dict[int, list[int]] = {}
    for r, authors in enumerate(graph.authors):
        for a in authors:
            works_of.setdefault(a, []).append(r)
    out = np.full(P.shape, np.nan, dtype=np.float64)
    for r, authors in enumerate(graph.authors):
        vecs = []
        for a in authors:
            others = [
                j
                for j in works_of[a]
                if j != r
                and usable[j]
                and abs(int(graph.years[j]) - int(graph.years[r])) <= cfg.author_window
            ]
            if others:
                vecs.append(P[others].mean(axis=0))
        if vecs:
            out[r] = np.mean(vecs, axis=0)
    return out


def matrices(
    probs: dict[int, dict[int, float]], graph: Graph, n_topics: int, cfg: PropagationConfig
) -> dict[str, np.ndarray]:
    """``{"prop_cite": ..., "prop_author": ...}`` from pass-1 probabilities."""
    P, usable = vectors_from_probs(probs, graph.n, n_topics)
    return {
        "prop_cite": prop_cite(P, usable, graph, cfg),
        "prop_author": prop_author(P, usable, graph, cfg),
    }


def attach(pairs: Pairs, mats: dict[str, np.ndarray]) -> dict[str, int]:
    """Fill the two ``prop_*`` columns of the pairs in place; returns the share of pairs filled."""
    counts = {}
    for name in PROP_FEATURES:
        col = FEATURES.index(name)
        pairs.X[:, col] = mats[name][pairs.work, pairs.topic].astype(np.float32)
        counts[name] = int((~np.isnan(pairs.X[:, col])).sum())
    return counts


def clear(pairs: Pairs) -> None:
    """Back to pass 1: the ``prop_*`` columns are NaN again."""
    for name in PROP_FEATURES:
        pairs.X[:, FEATURES.index(name)] = np.nan
