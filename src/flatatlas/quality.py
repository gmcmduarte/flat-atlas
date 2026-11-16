"""Data-quality checks on the resolved tables (``flatatlas evaluate --data``, P1-04).

Each check is one SQL query returning a count of offending rows (or a share) that is compared
with a threshold. Results go to ``ops_quality_report``; the command fails if any check failed,
so a broken resolve is loud. Informational rows (the merge-confidence histogram) have no
threshold and always pass.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import duckdb

from flatatlas.resolve.config import QualityConfig


@dataclass(frozen=True)
class CheckResult:
    check: str
    value: float
    threshold: float | None
    passed: bool
    detail: str = ""


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> float:
    row = con.execute(sql).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


def _zero(check: str, con: duckdb.DuckDBPyConnection, sql: str, detail: str) -> CheckResult:
    value = _scalar(con, sql)
    return CheckResult(check, value, 0.0, value == 0, detail)


def run_checks(con: duckdb.DuckDBPyConnection, cfg: QualityConfig) -> list[CheckResult]:
    """Run every check. Raises ``LookupError`` if the resolve stage has not been run."""
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    needed = {
        "core_work",
        "core_version",
        "core_author",
        "core_authorship",
        "core_venue",
        "core_edition",
        "core_citation",
        "core_version_match",
        "core_version_pair",
        "core_id_registry",
        "stg_dblp_paper",
    }
    if needed - have:
        raise LookupError(f"missing tables {sorted(needed - have)}: run `flatatlas resolve` first")
    results: list[CheckResult] = [
        _zero(
            "unique_dois_across_works",
            con,
            """SELECT count(*) FROM (SELECT doi FROM core_version WHERE doi IS NOT NULL
               GROUP BY doi HAVING count(DISTINCT work_id) > 1)""",
            "DOIs that appear on versions of more than one work",
        ),
        _zero(
            "versions_have_venue_and_year",
            con,
            """SELECT count(*) FROM core_version v
               LEFT JOIN core_venue ve USING (venue_id)
               LEFT JOIN core_edition ed ON ed.edition_id = v.edition_id
               WHERE v.year IS NULL OR v.venue_id IS NULL OR ve.venue_id IS NULL
                  OR v.edition_id IS NULL OR ed.edition_id IS NULL OR ed.venue_id <> v.venue_id""",
            "versions without a year, venue or edition, or whose edition belongs to another venue",
        ),
        _zero(
            "version_year_matches_edition",
            con,
            """SELECT count(*) FROM core_version v JOIN core_edition ed USING (edition_id)
               WHERE v.year <> ed.year""",
            "versions whose year differs from their edition's year",
        ),
        _zero(
            "no_orphan_authorships",
            con,
            """SELECT count(*) FROM core_authorship a
               LEFT JOIN core_version v USING (version_id)
               LEFT JOIN core_author au USING (author_id)
               WHERE v.version_id IS NULL OR au.author_id IS NULL""",
            "authorships whose version or author does not exist",
        ),
        _zero(
            "no_authors_without_authorship",
            con,
            """SELECT count(*) FROM core_author au
               WHERE NOT EXISTS (
                 SELECT 1 FROM core_authorship a WHERE a.author_id = au.author_id)""",
            "authors that appear on no version",
        ),
        _zero(
            "edition_counts_match_staging",
            con,
            """SELECT count(*) FROM (
                 SELECT ed.dblp_toc_key,
                        (SELECT count(*) FROM core_version v
                          WHERE v.edition_id = ed.edition_id) AS n_core,
                        (SELECT count(*) FROM stg_dblp_paper p
                          WHERE p.edition_key = ed.dblp_toc_key AND NOT p.is_front_matter) AS n_stg
                 FROM core_edition ed) WHERE n_core <> n_stg""",
            "editions whose version count differs from the staging papers (front matter left out)",
        ),
        _zero(
            "one_pid_per_author",
            con,
            """SELECT
                 (SELECT count(*) FROM core_author WHERE dblp_pid IS NULL)
               + (SELECT count(*) FROM (SELECT dblp_pid FROM core_author GROUP BY dblp_pid
                                        HAVING count(*) > 1))
               + (SELECT count(*) FROM (SELECT oa FROM (SELECT unnest(openalex_ids) AS oa
                                                         FROM core_author)
                                        GROUP BY oa HAVING count(*) > 1))""",
            "authors without a PID, PIDs on two authors, OpenAlex IDs on two authors",
        ),
        _zero(
            "works_are_consistent",
            con,
            """SELECT
                 (SELECT count(*) FROM core_work w
                    LEFT JOIN core_version v ON v.version_id = w.primary_version_id
                    WHERE v.version_id IS NULL OR v.work_id <> w.work_id)
               + (SELECT count(*) FROM core_version v
                    LEFT JOIN core_work w USING (work_id) WHERE w.work_id IS NULL)
               + (SELECT count(*) FROM core_work w
                    JOIN (SELECT work_id, min(year) AS y FROM core_version GROUP BY work_id) m
                      USING (work_id) WHERE w.year <> m.y)""",
            "works without their primary version, versions without a work, year not the earliest",
        ),
        _zero(
            "no_merged_away_ids_in_tables",
            con,
            """SELECT count(*) FROM core_id_registry r
               WHERE r.merged_into IS NOT NULL AND (
                    r.atlas_id IN (SELECT work_id FROM core_work)
                 OR r.atlas_id IN (SELECT work_id FROM core_version)
                 OR r.atlas_id IN (SELECT citing_work_id FROM core_citation)
                 OR r.atlas_id IN (SELECT cited_work_id FROM core_citation))""",
            "merged-away IDs still used in a table",
        ),
        _zero(
            "citations_are_valid",
            con,
            """SELECT count(*) FROM core_citation c
               WHERE c.citing_work_id = c.cited_work_id
                  OR c.citing_work_id NOT IN (SELECT work_id FROM core_work)
                  OR c.cited_work_id NOT IN (SELECT work_id FROM core_work)""",
            "self-citations and edges whose end is not a work",
        ),
    ]

    uncertain = _scalar(con, "SELECT count(*) FROM core_version_pair WHERE verdict = 'uncertain'")
    results.append(
        CheckResult(
            "uncertain_version_pairs",
            uncertain,
            float(cfg.max_uncertain_pairs),
            uncertain <= cfg.max_uncertain_pairs,
            "pairs scored between report_min and merge_min (listed in the report, not merged)",
        )
    )

    n_versions = _scalar(con, "SELECT count(*) FROM core_version")
    for source, floor in (
        ("openalex", cfg.min_share_openalex),
        ("s2", cfg.min_share_s2),
    ):
        matched = _scalar(
            con,
            f"SELECT count(DISTINCT version_id) FROM core_version_match WHERE source = '{source}'",
        )
        share = matched / n_versions if n_versions else 0.0
        results.append(
            CheckResult(
                f"share_matched_{source}",
                share,
                floor,
                share >= floor,
                f"{int(matched)} of {int(n_versions)} versions",
            )
        )
    with_doi = _scalar(con, "SELECT count(*) FROM core_version WHERE doi IS NOT NULL")
    cr = _scalar(
        con,
        """SELECT count(DISTINCT m.version_id) FROM core_version_match m
           JOIN core_version v USING (version_id)
           WHERE m.source = 'crossref' AND v.doi IS NOT NULL""",
    )
    cr_share = cr / with_doi if with_doi else 0.0
    results.append(
        CheckResult(
            "share_matched_crossref_of_doi",
            cr_share,
            cfg.min_share_crossref_of_doi,
            cr_share >= cfg.min_share_crossref_of_doi,
            f"{int(cr)} of {int(with_doi)} versions with a DOI",
        )
    )

    results.extend(_histogram(con, cfg.histogram_edges))
    return results


def _histogram(con: duckdb.DuckDBPyConnection, edges: list[float]) -> list[CheckResult]:
    """Versions attached by a scored pair, by merge confidence; plus the number of founders."""
    rows: list[CheckResult] = [
        CheckResult(
            "merge_confidence_anchor",
            _scalar(con, "SELECT count(*) FROM core_version WHERE merge_method = 'anchor'"),
            None,
            True,
            "versions that founded their work (confidence 1.0)",
        )
    ]
    last = len(edges) - 1
    for i, (lo, hi) in enumerate(zip(edges, edges[1:], strict=False)):
        upper = "<=" if i == last - 1 else "<"
        n = _scalar(
            con,
            f"""SELECT count(*) FROM core_version WHERE merge_method <> 'anchor'
                AND merge_confidence >= {lo} AND merge_confidence {upper} {hi}""",
        )
        bracket = "]" if upper == "<=" else ")"
        rows.append(
            CheckResult(
                f"merge_confidence_hist[{lo:g},{hi:g}{bracket}",
                n,
                None,
                True,
                "versions merged into a work",
            )
        )
    return rows


def record(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    results: list[CheckResult],
    *,
    log: Callable[[str], None] | None = None,
) -> None:
    """Store the results in ``ops_quality_report`` (the rows of this ``run_id`` are replaced)."""
    con.execute("DELETE FROM ops_quality_report WHERE run_id = ?", [run_id])
    for r in results:
        con.execute(
            'INSERT INTO ops_quality_report (run_id, "check", value, threshold, passed) '
            "VALUES (?, ?, ?, ?, ?)",
            [run_id, r.check, r.value, r.threshold, r.passed],
        )
        if log is not None:
            log(f"{'ok  ' if r.passed else 'FAIL'} {r.check}: {r.value:g} ({r.detail})")
