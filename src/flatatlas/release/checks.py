"""Checks a release must pass before any file is written (P1-09).

Three groups: the data-quality checks on the resolved tables (``quality.run_checks``), the hard
checks of the adopted tagging variant, read from the frozen record of P1-08 (no held-out label is
read; ``evaluate check`` does the same), and the structure of what is about to be released.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import duckdb

from flatatlas import quality
from flatatlas.evaluate import freeze as freeze_mod
from flatatlas.evaluate.commands import adopted_key
from flatatlas.quality import CheckResult
from flatatlas.resolve.config import load_resolve_config
from flatatlas.tagging.config import TaggerConfig

# Column names that would mean text or vectors of a paper are leaving the machine (PLAN §4.7).
FORBIDDEN_COLUMN = re.compile(r"abstract|tldr|embedding|vector|full_?text|^text$", re.IGNORECASE)
ALLOWED_COLUMNS = {"has_abstract"}  # a flag, not the text
# Signals that belong to steps the pilot does not ship (D-100): not in a released tag.
UNSHIPPED_SIGNALS = re.compile(r"^(dm_|prop_|distil)")


class ReleaseError(RuntimeError):
    """A release check failed; the message lists every failure."""


def data_quality(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    return quality.run_checks(con, load_resolve_config().quality)


def tagger_checks(reports: Path, cfg: TaggerConfig) -> list[CheckResult]:
    """The adopted variant's anchors, coverage, stability and venue sanity (frozen record)."""
    path = freeze_mod.frozen_path(reports, freeze_mod.default_run_id(cfg))
    if not path.exists():
        raise ReleaseError(f"no frozen record {path}; run `flatatlas evaluate freeze` first")
    frozen = json.loads(path.read_text("utf-8"))
    key = adopted_key(cfg)
    return [r for r in freeze_mod.results_for_ops(frozen, cfg, key) if r.check.endswith(f"[{key}]")]


def forbidden_columns(columns: list[str]) -> list[str]:
    """The column names (flattened struct fields included) a release must not contain."""
    return [
        c
        for c in columns
        if c not in ALLOWED_COLUMNS and FORBIDDEN_COLUMN.search(c.rsplit(".", 1)[-1])
    ]


def tag_structure(con: duckdb.DuckDBPyConnection, view: str, cfg: TaggerConfig) -> list[str]:
    """Problems in the released tag rows: another method, another version, unshipped signals."""
    problems = []
    methods = {
        r[0] for r in con.execute(f"SELECT DISTINCT provenance.method FROM {view}").fetchall()
    }
    if methods != {cfg.method}:
        problems.append(f"work_topics holds methods {sorted(methods)}, expected only {cfg.method}")
    versions = {
        r[0]
        for r in con.execute(f"SELECT DISTINCT provenance.tagger_version FROM {view}").fetchall()
    }
    if versions != {cfg.tagger_version}:
        problems.append(f"work_topics holds tagger versions {sorted(versions)}")
    names = {
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT s.name FROM (SELECT unnest(provenance.signals) AS s FROM {view})"
        ).fetchall()
    }
    bad = sorted(n for n in names if UNSHIPPED_SIGNALS.search(n))
    if bad:
        problems.append(f"work_topics carries signals of steps that are off: {bad}")
    return problems
