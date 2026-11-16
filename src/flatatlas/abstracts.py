"""Which abstract a paper uses when several sources have one (P1-03).

``local_abstract`` keeps one row per paper and source. Reading code goes through
``best_abstracts`` so the priority lives in one place: OpenAlex, then Semantic Scholar, then
Crossref (the order of the P1-03 prompt). Abstracts are local-use data and never exported
(CLAUDE.md rule 2).
"""

from __future__ import annotations

import duckdb

ABSTRACT_PRIORITY = ("openalex", "s2", "crossref")


def best_abstracts(con: duckdb.DuckDBPyConnection) -> dict[str, tuple[str, str]]:
    """``dblp_key -> (source, text)``: the highest-priority non-empty abstract of each paper."""
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "local_abstract" not in tables:
        return {}
    rank = {source: i for i, source in enumerate(ABSTRACT_PRIORITY)}
    best: dict[str, tuple[int, str, str]] = {}
    for key, source, text in con.execute(
        "SELECT dblp_key, source, text FROM local_abstract WHERE text IS NOT NULL AND text <> ''"
    ).fetchall():
        r = rank.get(source, len(rank))
        if key not in best or r < best[key][0]:
            best[key] = (r, source, text)
    return {key: (source, text) for key, (_r, source, text) in best.items()}
