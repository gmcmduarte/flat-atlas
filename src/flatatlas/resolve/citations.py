"""``core_citation``: edges between works of the corpus, from OpenAlex and Semantic Scholar."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


def build_citation_rows(
    oa_edges: Iterable[tuple[str, str]],
    s2_edges: Iterable[tuple[int, int]],
    oa_to_work: Mapping[str, str],
    s2_to_work: Mapping[int, str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Union of both sources, one row per ordered pair of works.

    An edge is kept only when both ends are works of the corpus. Several versions of one work
    cite and are cited as that work, so edges are lifted to works; a work citing itself through
    two of its versions is dropped. ``is_influential`` stays null: Semantic Scholar gives that
    flag per edge only on a per-paper endpoint that is not harvested (D-68).
    """
    sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    stats = {"openalex_edges_seen": 0, "openalex_in_corpus": 0, "s2_edges_seen": 0}
    stats.update({"s2_in_corpus": 0, "self_citations_dropped": 0})
    for citing, cited in oa_edges:
        stats["openalex_edges_seen"] += 1
        a, b = oa_to_work.get(citing), oa_to_work.get(cited)
        if a is None or b is None:
            continue
        stats["openalex_in_corpus"] += 1
        if a == b:
            stats["self_citations_dropped"] += 1
            continue
        sources[(a, b)].add("openalex")
    for citing, cited in s2_edges:
        stats["s2_edges_seen"] += 1
        a, b = s2_to_work.get(citing), s2_to_work.get(cited)
        if a is None or b is None:
            continue
        stats["s2_in_corpus"] += 1
        if a == b:
            stats["self_citations_dropped"] += 1
            continue
        sources[(a, b)].add("s2")
    rows = [
        {
            "citing_work_id": a,
            "cited_work_id": b,
            "sources": sorted(src),
            "is_influential": None,
        }
        for (a, b), src in sorted(sources.items())
    ]
    stats["edges"] = len(rows)
    stats["edges_in_both_sources"] = sum(1 for r in rows if len(r["sources"]) == 2)
    return rows, stats
