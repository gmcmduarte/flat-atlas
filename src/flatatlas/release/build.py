"""Build a versioned release folder (PLAN §4.7, §10; P1-09).

``releases/v<YYYY.MM.patch>/`` holds Parquet files of the public tables, ``manifest.json`` (row
counts, SHA-256 per file, versions, source dates, check results), ``SOURCES.md``, ``LICENSE.md``
and ``CITATION.cff``. Nothing is written unless every check passes. A release never holds an
abstract, a TLDR or an embedding, and carries only the shipped tagging method's rows.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from flatatlas import __version__
from flatatlas.db import write_query_parquet_atomic, write_text_atomic
from flatatlas.quality import CheckResult, record
from flatatlas.release import checks
from flatatlas.release.checks import ReleaseError
from flatatlas.settings import PROJECT_ROOT, Paths
from flatatlas.tagging.config import TaggerConfig

REPOSITORY = "https://github.com/gmcmduarte/flat-atlas"

# release file -> the query that produces it. ``{method}`` is the shipped tagging method.
TABLES: dict[str, str] = {
    "works.parquet": (
        "SELECT w.*, CASE WHEN t.work_id IS NULL THEN 'untagged' "
        "WHEN t.low THEN 'low_confidence' ELSE 'tagged' END AS tag_status "
        "FROM core_work w LEFT JOIN (SELECT work_id, "
        "bool_or(list_contains(COALESCE(provenance.flags, []), 'low_confidence')) AS low "
        "FROM tag_work_topic WHERE provenance.method = '{method}' GROUP BY work_id) t "
        "ON t.work_id = w.work_id ORDER BY w.work_id"
    ),
    "versions.parquet": "SELECT * FROM core_version ORDER BY version_id",
    "authors.parquet": "SELECT * FROM core_author ORDER BY author_id",
    "authorships.parquet": "SELECT * FROM core_authorship ORDER BY version_id, position",
    "institutions.parquet": "SELECT * FROM core_institution ORDER BY institution_id",
    "venues.parquet": "SELECT * FROM core_venue ORDER BY venue_id",
    "editions.parquet": "SELECT * FROM core_edition ORDER BY edition_id",
    "citations.parquet": "SELECT * FROM core_citation ORDER BY citing_work_id, cited_work_id",
    "topics.parquet": "SELECT * FROM core_topic ORDER BY topic_id",
    "topic_edges.parquet": (
        "SELECT * FROM core_topic_edge ORDER BY edge_type, src_topic, dst_topic"
    ),
    "work_topics.parquet": (
        "SELECT * FROM tag_work_topic WHERE provenance.method = '{method}' "
        "ORDER BY work_id, rank, topic_id"
    ),
    "agg_topic_year.parquet": "SELECT * FROM agg_topic_year ORDER BY topic_id, year",
    "agg_topic_author.parquet": "SELECT * FROM agg_topic_author ORDER BY topic_id, author_id",
    "agg_topic_venue.parquet": "SELECT * FROM agg_topic_venue ORDER BY topic_id, venue_id",
    "agg_topic_work.parquet": "SELECT * FROM agg_topic_work ORDER BY topic_id, rank",
    "agg_map_layout.parquet": "SELECT * FROM agg_map_layout ORDER BY topic_id",
    "id_registry.parquet": "SELECT * FROM core_id_registry ORDER BY atlas_id",
}

LICENSE_TEXT = """# License

The data in this release is licensed under the **Creative Commons Attribution 4.0 International**
licence (CC BY 4.0): https://creativecommons.org/licenses/by/4.0/legalcode

You may share and adapt it, including commercially, if you give appropriate credit, link to the
licence and say what you changed. Credit "The FLAT Atlas" (see `CITATION.cff`) **and** the sources
listed in `SOURCES.md`; those sources have their own terms, which CC BY 4.0 satisfies as long as the
attribution is kept.

This release holds metadata and links only. It contains no abstracts, no full texts and no
embeddings. Topic tags are our own derived judgments, each with a confidence and its provenance.

The code that builds the data is licensed under the MIT licence (see the repository).
This is a plain-language summary and not legal advice.
"""

SOURCES_TEXT = """# Sources and attribution

This release combines metadata from the following sources. Keep these credits when you reuse it.

- **DBLP** (https://dblp.org): paper, author, venue and edition metadata, from the official
  XML dump. Released under CC0 1.0.
- **OpenAlex** (https://openalex.org): identifiers, citation links, open-access locations and topic
  hints. Released under CC0 1.0.
- **Crossref** (https://www.crossref.org): DOIs and bibliographic metadata, used under Crossref's
  terms for metadata reuse.
- **Semantic Scholar** (https://www.semanticscholar.org): citation links, citation counts and
  identifiers. Open data under the ODC-BY licence. Please cite: Kinney et al., "The Semantic
  Scholar Open Data Platform", 2023 (arXiv:2301.10140).

Topic tags, topic edges, aggregates and the map layout are computed by The FLAT Atlas pipeline
(tagger `{tagger_version}`, taxonomy version {taxonomy_version}, aggregates `{aggregate_version}`).
Abstracts and embeddings used while tagging are not part of this release.

Fetch dates (the last time each source was queried):

{fetch_dates}
"""

CITATION_TEXT = """cff-version: 1.2.0
message: "If you use this dataset, please cite it as below."
title: "The FLAT Atlas: a map of formal languages and automata theory"
type: dataset
version: "{version}"
date-released: "{date}"
license: CC-BY-4.0
repository-code: "{repository}"
authors:
  - family-names: "Duarte"
    given-names: "Guilherme"
"""


@dataclass(frozen=True)
class ReleaseResult:
    path: Path
    version: str
    manifest: dict


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def next_version(releases: Path, today: datetime) -> str:
    """``vYYYY.MM.patch``: the patch counts the releases already made this month."""
    prefix = f"v{today:%Y.%m}."
    existing = [p.name for p in releases.glob(f"{prefix}*") if p.is_dir()]
    patches = [int(n.rsplit(".", 1)[1]) for n in existing if n.rsplit(".", 1)[1].isdigit()]
    return f"{prefix}{max(patches) + 1 if patches else 0}"


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def git_commit() -> str | None:
    return _git("rev-parse", "HEAD")


def git_dirty() -> bool | None:
    """True when the working tree has uncommitted changes (the commit then does not say it all)."""
    status = _git("status", "--porcelain")
    return None if status is None else bool(status)


def source_dates(con: duckdb.DuckDBPyConnection, paths: Paths) -> dict[str, str]:
    """Last harvest time per source, and the date of the DBLP dump file on disk."""
    dates = {
        r[0]: f"{r[1]:%Y-%m-%d}"
        for r in con.execute(
            "SELECT source, max(updated_at) FROM ops_harvest_state GROUP BY source ORDER BY source"
        ).fetchall()
        if r[1] is not None
    }
    dump = paths.raw / "dblp-dump" / "dblp.xml.gz"
    if dump.exists():
        dates["dblp-dump"] = f"{datetime.fromtimestamp(dump.stat().st_mtime, UTC):%Y-%m-%d}"
    return dates


def _columns(path: Path) -> list[str]:
    """Every column name in a Parquet file, struct fields included (dotted)."""
    schema = pq.ParquetFile(path).schema
    return [schema.column(i).path for i in range(len(schema))]


def build(
    con: duckdb.DuckDBPyConnection,
    paths: Paths,
    tagger_cfg: TaggerConfig,
    *,
    aggregate_version: str,
    taxonomy_version: int,
    today: datetime | None = None,
) -> ReleaseResult:
    """Run the checks, then write the release folder. Raises ``ReleaseError`` on any failure."""
    today = today or datetime.now(UTC)
    results: list[CheckResult] = checks.data_quality(con) + checks.tagger_checks(
        paths.reports, tagger_cfg
    )
    failed = [r for r in results if not r.passed]
    if failed:
        raise ReleaseError(
            "checks failed: " + "; ".join(f"{r.check}={r.value:g} ({r.detail})" for r in failed)
        )
    version = next_version(paths.releases, today)
    record(con, f"release-{version}", results)

    problems = checks.tag_structure(
        con,
        f"(SELECT * FROM tag_work_topic WHERE provenance.method = '{tagger_cfg.method}')",
        tagger_cfg,
    )
    if problems:
        raise ReleaseError("; ".join(problems))

    target = paths.releases / version
    tmp = paths.releases / f".{version}.partial"
    if tmp.exists():
        for old in tmp.iterdir():
            old.unlink()
    tmp.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict] = {}
    try:
        for name, query in TABLES.items():
            path = tmp / name
            write_query_parquet_atomic(con, query.format(method=tagger_cfg.method), path)
            bad = checks.forbidden_columns(_columns(path))
            if bad:
                raise ReleaseError(f"{name} has forbidden columns: {bad}")
            files[name] = {
                "rows": pq.ParquetFile(path).metadata.num_rows,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        dates = source_dates(con, paths)
        classes = dict(
            con.execute(
                "SELECT tag_status, count(*) FROM read_parquet(?) GROUP BY 1 ORDER BY 1",
                [str(tmp / "works.parquet")],
            ).fetchall()
        )
        fetch_lines = "\n".join(f"- {s}: {d}" for s, d in sorted(dates.items())) or "- (none)"
        docs = {
            "SOURCES.md": SOURCES_TEXT.format(
                tagger_version=tagger_cfg.tagger_version,
                taxonomy_version=taxonomy_version,
                aggregate_version=aggregate_version,
                fetch_dates=fetch_lines,
            ),
            "LICENSE.md": LICENSE_TEXT,
            "CITATION.cff": CITATION_TEXT.format(
                version=version, date=f"{today:%Y-%m-%d}", repository=REPOSITORY
            ),
        }
        for name, text in docs.items():
            write_text_atomic(tmp / name, text)
            files[name] = {
                "rows": None,
                "bytes": (tmp / name).stat().st_size,
                "sha256": sha256_file(tmp / name),
            }
        manifest = {
            "version": version,
            "date": f"{today:%Y-%m-%d}",
            "flatatlas": __version__,
            "git_commit": git_commit(),
            "git_dirty": git_dirty(),
            "tagger_version": tagger_cfg.tagger_version,
            "tagging_method": tagger_cfg.method,
            "taxonomy_version": taxonomy_version,
            "aggregate_version": aggregate_version,
            "works_by_tag_status": classes,
            "source_fetch_dates": dates,
            "checks": [
                {"check": r.check, "value": r.value, "threshold": r.threshold, "passed": r.passed}
                for r in results
            ],
            "files": files,
        }
        write_text_atomic(tmp / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        if target.exists():
            raise ReleaseError(f"{target} already exists")
        tmp.rename(target)
    except BaseException:
        for leftover in tmp.glob("*"):
            leftover.unlink(missing_ok=True)
        tmp.rmdir()
        raise
    return ReleaseResult(target, version, manifest)


def verify(release: Path) -> list[str]:
    """Problems found when the manifest is checked against the files (an empty list is a pass)."""
    manifest_path = release / "manifest.json"
    if not manifest_path.exists():
        return [f"{manifest_path} is missing"]
    manifest = json.loads(manifest_path.read_text("utf-8"))
    problems = []
    for name, info in manifest["files"].items():
        path = release / name
        if not path.exists():
            problems.append(f"{name} is missing")
            continue
        if sha256_file(path) != info["sha256"]:
            problems.append(f"{name}: checksum differs from the manifest")
            continue  # the file cannot be trusted, so it is not opened
        if info.get("rows") is not None and pq.ParquetFile(path).metadata.num_rows != info["rows"]:
            problems.append(f"{name}: row count differs from the manifest")
        if name.endswith(".parquet"):
            bad = checks.forbidden_columns(_columns(path))
            if bad:
                problems.append(f"{name}: forbidden columns {bad}")
    extra = {p.name for p in release.iterdir()} - set(manifest["files"]) - {"manifest.json"}
    if extra:
        problems.append(f"files not in the manifest: {sorted(extra)}")
    return problems
