"""The pilot coverage report (P1-02): how much metadata do the open sources give for each venue?

Everything is computed from the warehouse tables of the DBLP, OpenAlex and Crossref parse stages,
so the report can be regenerated at any time without the network. ``render`` is pure.

The unit is a DBLP paper (front matter left out). Shares use *all* papers of the cell as the
denominator, except the matching rates, which say what they are divided by. Counts of papers a
stage did not fetch yet are reported, so a partial run cannot pass for a full one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import duckdb
import pyarrow as pa

from flatatlas.sources import crossref, openalex

BASE_SQL = """
WITH paper AS (
    SELECT
        p.dblp_key,
        p.venue_id,
        (p.year // 10) * 10 AS decade,
        p.doi IS NOT NULL AS has_doi,
        coalesce(l.fetched, false) AS fetched,
        l.openalex_id IS NOT NULL AS matched,
        l.match_method AS match_method,
        coalesce(w.has_abstract, false) AS abs_openalex,
        EXISTS (SELECT 1 FROM local_abstract a
                WHERE a.dblp_key = p.dblp_key AND a.source = 'crossref') AS abs_crossref,
        coalesce(w.n_references_listed, 0) > 0 AS refs_openalex,
        coalesce(c.n_references_listed, 0) > 0 AS refs_crossref,
        coalesce(w.n_authors_with_institution, 0) > 0 AS has_affiliation,
        coalesce(w.n_authors_with_country, 0) > 0 AS has_country,
        w.first_page IS NOT NULL OR c.first_page IS NOT NULL AS has_pages
    FROM stg_dblp_paper p
    LEFT JOIN stg_openalex_lookup l ON l.dblp_key = p.dblp_key
    LEFT JOIN stg_openalex_work w ON w.openalex_id = l.openalex_id
    LEFT JOIN stg_crossref_work c ON c.doi = lower(p.doi)
    WHERE NOT p.is_front_matter
)
SELECT
    {group_cols}
    count(*) AS papers,
    count(*) FILTER (WHERE has_doi) AS with_doi,
    count(*) FILTER (WHERE fetched) AS fetched,
    count(*) FILTER (WHERE has_doi AND fetched) AS doi_fetched,
    count(*) FILTER (WHERE has_doi AND matched) AS doi_matched,
    count(*) FILTER (WHERE NOT has_doi AND fetched) AS nodoi_fetched,
    count(*) FILTER (WHERE NOT has_doi AND matched) AS nodoi_matched,
    count(*) FILTER (WHERE matched) AS matched,
    count(*) FILTER (WHERE abs_openalex) AS abs_openalex,
    count(*) FILTER (WHERE abs_crossref) AS abs_crossref,
    count(*) FILTER (WHERE abs_openalex OR abs_crossref) AS abs_any,
    count(*) FILTER (WHERE refs_openalex) AS refs_openalex,
    count(*) FILTER (WHERE refs_crossref) AS refs_crossref,
    count(*) FILTER (WHERE refs_openalex OR refs_crossref) AS refs_any,
    count(*) FILTER (WHERE has_affiliation) AS has_affiliation,
    count(*) FILTER (WHERE has_country) AS has_country,
    count(*) FILTER (WHERE has_pages) AS has_pages
FROM paper
{group_by}
ORDER BY {order}
"""


def _empty(schema: pa.Schema) -> pa.Table:
    return pa.Table.from_pylist([], schema=schema)


def ensure_inputs(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Register empty stand-ins for tables a stage has not produced yet; return their names."""
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    required = {"stg_dblp_paper", "stg_openalex_lookup", "stg_openalex_work"}
    missing_required = sorted(required - have)
    if missing_required:
        raise LookupError(
            "missing table(s): " + ", ".join(missing_required) + " (run `flatatlas parse dblp` and "
            "`flatatlas parse openalex` first)"
        )
    stand_ins: dict[str, pa.Schema] = {
        "stg_crossref_work": crossref.SCHEMA,
        "local_abstract": openalex.LOCAL_ABSTRACT_SCHEMA,
    }
    registered = []
    for name, schema in stand_ins.items():
        if name not in have:
            con.register(name, _empty(schema))
            registered.append(name)
    return registered


@dataclass
class Coverage:
    cells: list[dict[str, Any]] = field(default_factory=list)  # venue x decade
    venues: list[dict[str, Any]] = field(default_factory=list)  # venue, all decades
    total: dict[str, Any] = field(default_factory=dict)
    missing_stages: list[str] = field(default_factory=list)
    unmatched_doi: list[dict[str, Any]] = field(default_factory=list)  # asked, not in OpenAlex
    generated_at: str = ""


def _rows(con: duckdb.DuckDBPyConnection, group_cols: str, group_by: str, order: str):
    cur = con.execute(BASE_SQL.format(group_cols=group_cols, group_by=group_by, order=order))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


UNMATCHED_LIMIT = 40


def _unmatched_doi(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    """Papers whose DOI was asked and not returned: the gap behind the DOI match rate."""
    cur = con.execute(
        f"""
        SELECT p.dblp_key, p.venue_id, p.year, p.doi
        FROM stg_dblp_paper p JOIN stg_openalex_lookup l ON l.dblp_key = p.dblp_key
        WHERE NOT p.is_front_matter AND p.doi IS NOT NULL AND l.fetched AND l.openalex_id IS NULL
        ORDER BY p.year DESC, p.dblp_key LIMIT {UNMATCHED_LIMIT}
        """
    )
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def compute(con: duckdb.DuckDBPyConnection, *, now: datetime | None = None) -> Coverage:
    registered = ensure_inputs(con)
    try:
        cov = Coverage(
            cells=_rows(con, "venue_id, decade,", "GROUP BY venue_id, decade", "venue_id, decade"),
            venues=_rows(con, "venue_id,", "GROUP BY venue_id", "venue_id"),
            total=_rows(con, "", "", "1")[0],
            missing_stages=[
                {"stg_crossref_work": "parse crossref", "local_abstract": "parse openalex"}[n]
                for n in registered
            ],
            unmatched_doi=_unmatched_doi(con),
            generated_at=(now or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC"),
        )
    finally:
        for name in registered:
            con.unregister(name)
    return cov


# -- rendering -----------------------------------------------------------------------------------


def pct(part: int, whole: int) -> str:
    return "–" if not whole else f"{part / whole:.0%}"


def _table(rows: Sequence[dict[str, Any]], first: Sequence[tuple[str, str]]) -> list[str]:
    head = [title for title, _ in first] + [
        "Papers",
        "DOI",
        "Matched",
        "Abstract OA",
        "Abstract CR",
        "Abstract any",
        "Refs any",
        "Affil.",
        "Country",
    ]
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    for r in rows:
        cells = [str(r[key]) if key != "decade" else f"{r[key]}s" for _, key in first]
        n = r["papers"]
        cells += [
            str(n),
            pct(r["with_doi"], n),
            pct(r["matched"], n),
            pct(r["abs_openalex"], n),
            pct(r["abs_crossref"], n),
            pct(r["abs_any"], n),
            pct(r["refs_any"], n),
            pct(r["has_affiliation"], n),
            pct(r["has_country"], n),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _unmatched_section(cov: Coverage) -> list[str]:
    t = cov.total
    gap = t["doi_fetched"] - t["doi_matched"]
    if not gap:
        return []
    shown = len(cov.unmatched_doi)
    lines = [
        f"## DOIs asked and not returned ({gap})",
        "",
        "OpenAlex answers a DOI filter only with works whose primary DOI it knows; a version "
        "merged into another record, or a paper it has not ingested yet, comes back empty.",
        "",
        *([] if shown >= gap else [f"The newest {shown} are listed.", ""]),
        "| DBLP key | Venue | Year | DOI |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {r['dblp_key']} | {r['venue_id']} | {r['year']} | {r['doi']} |"
        for r in cov.unmatched_doi
    ]
    return [*lines, ""]


def render(cov: Coverage, *, profile: str = "pilot", dblp_note: str = "") -> str:
    t = cov.total
    n = t["papers"]
    lines = [
        f"# Coverage report: {profile} venues",
        "",
        f"Generated {cov.generated_at} by `flatatlas evaluate coverage`. "
        "Regenerate it; do not edit.",
        "",
        "## Summary",
        "",
        f"- **Papers:** {n} DBLP papers (front matter left out), {t['with_doi']} with a DOI "
        f"({pct(t['with_doi'], n)}). {dblp_note}".rstrip(),
        f"- **Looked up in OpenAlex:** {t['fetched']} of {n} papers "
        f"({t['doi_fetched']} by DOI, {t['nodoi_fetched']} by title search).",
        f"- **DOI match rate:** {t['doi_matched']} of {t['doi_fetched']} fetched papers with a DOI "
        f"are in OpenAlex ({pct(t['doi_matched'], t['doi_fetched'])}).",
        f"- **Title-search match rate:** {t['nodoi_matched']} of {t['nodoi_fetched']} fetched "
        f"papers without a DOI ({pct(t['nodoi_matched'], t['nodoi_fetched'])}); accepted at "
        f"normalised title similarity of at least {openalex.TITLE_MATCH_MIN} and a year within "
        f"{openalex.TITLE_YEAR_SLACK}.",
        f"- **Abstracts (any source):** {t['abs_any']} of {n} ({pct(t['abs_any'], n)}): "
        f"OpenAlex {t['abs_openalex']} ({pct(t['abs_openalex'], n)}), "
        f"Crossref {t['abs_crossref']} ({pct(t['abs_crossref'], n)}). Semantic Scholar is added "
        "in P1-03.",
        f"- **Reference lists:** {t['refs_any']} of {n} ({pct(t['refs_any'], n)}): "
        f"OpenAlex {t['refs_openalex']}, Crossref {t['refs_crossref']}.",
        f"- **Affiliations / countries (OpenAlex):** {t['has_affiliation']} / {t['has_country']} "
        f"of {n} ({pct(t['has_affiliation'], n)} / {pct(t['has_country'], n)}).",
    ]
    if t["fetched"] < n:
        lines += [
            "",
            f"> **Partial run:** {n - t['fetched']} of {n} papers have not been looked up in "
            "OpenAlex yet; their cells count as missing.",
        ]
    if cov.missing_stages:
        lines += [
            "",
            f"> **Not run yet:** `flatatlas {'`, `flatatlas '.join(cov.missing_stages)}` "
            "(the columns it feeds read as zero).",
        ]
    lines += [
        "",
        "## By venue",
        "",
        *_table(cov.venues, [("Venue", "venue_id")]),
        "",
        "## By venue and decade",
        "",
        *_table(cov.cells, [("Venue", "venue_id"), ("Decade", "decade")]),
        "",
        *_unmatched_section(cov),
        "## How to read this",
        "",
        "- The unit is a DBLP paper; DBLP decides which papers belong to a venue (PLAN §8.4).",
        "- Every percentage is of all papers in its row, except the match rates in the summary.",
        "- *DOI*: share of papers with a DOI in DBLP. *Matched*: share found in OpenAlex.",
        "- *Abstract OA / CR*: an abstract text from OpenAlex / Crossref. Abstracts stay in the "
        "local warehouse and are not exported (CLAUDE.md rule 2).",
        "- *Refs any*: a non-empty reference list in OpenAlex or Crossref.",
        "- *Affil.* / *Country*: at least one author with an institution / country in OpenAlex.",
        "",
    ]
    return "\n".join(lines)
