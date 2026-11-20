"""``flatatlas release build | verify`` (P1-09); ``cli.py`` registers them on its group."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import duckdb
import typer

from flatatlas.aggregate.config import load_config as load_aggregate_config
from flatatlas.db import connect, run_log
from flatatlas.log import setup_logging
from flatatlas.release import build as build_mod
from flatatlas.release.checks import ReleaseError
from flatatlas.settings import load_settings
from flatatlas.tagging.config import load_config as load_tagger_config
from flatatlas.taxonomy.check import TOPICS_FILE, load_topics

ProfileOption = Annotated[
    str | None, typer.Option(help="Profile name (default: FLATATLAS_PROFILE or pilot).")
]


def build(profile: ProfileOption = None) -> None:
    """Check the data, then write releases/v<YYYY.MM.patch>/ (refuses if a check fails)."""
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    tagger_cfg = load_tagger_config()
    agg_cfg = load_aggregate_config()
    if not settings.paths.warehouse_db.exists():
        typer.echo("error: no warehouse; run the earlier stages first", err=True)
        raise typer.Exit(1)
    con = connect(settings.paths)
    try:
        with run_log(con, "release-build") as run:
            try:
                result = build_mod.build(
                    con,
                    settings.paths,
                    tagger_cfg,
                    aggregate_version=agg_cfg.aggregate_version,
                    taxonomy_version=load_topics(TOPICS_FILE).taxonomy_version,
                )
            except (ReleaseError, LookupError, duckdb.CatalogException) as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(1) from None
            run.counts.update(version=result.version, files=str(len(result.manifest["files"])))
    finally:
        con.close()
    problems = build_mod.verify(result.path)
    if problems:
        for p in problems:
            typer.echo(f"error: {p}", err=True)
        raise typer.Exit(1)
    size = sum(f["bytes"] for f in result.manifest["files"].values())
    typer.echo(f"wrote {result.path} ({len(result.manifest['files'])} files, {size / 1e6:.1f} MB)")
    typer.echo(f"works by tag status: {result.manifest['works_by_tag_status']}")


def verify(
    release: Annotated[
        Path, typer.Argument(help="A release folder, for example releases/v2026.11.0.")
    ],
) -> None:
    """Check a release folder against its manifest (checksums, row counts, forbidden columns)."""
    problems = build_mod.verify(release)
    for p in problems:
        typer.echo(f"error: {p}", err=True)
    if problems:
        raise typer.Exit(1)
    typer.echo(f"{release}: manifest verified")
