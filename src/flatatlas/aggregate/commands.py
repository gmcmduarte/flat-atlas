"""The ``flatatlas aggregate`` command (P1-09); ``cli.py`` registers it on its group."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from flatatlas.aggregate import edges as edge_mod
from flatatlas.aggregate import stage
from flatatlas.aggregate.config import CONFIG_FILE, load_config
from flatatlas.db import connect, run_log
from flatatlas.log import setup_logging
from flatatlas.settings import load_settings
from flatatlas.tagging.config import load_config as load_tagger_config
from flatatlas.taxonomy.stage import MissingInput

ProfileOption = Annotated[
    str | None, typer.Option(help="Profile name (default: FLATATLAS_PROFILE or pilot).")
]


def aggregate_run(
    ctx: typer.Context,
    limit: Annotated[
        int | None, typer.Option(help="Use only the first N works by ID (a quick test).")
    ] = None,
    config: Annotated[Path | None, typer.Option("--config", help="Aggregate settings.")] = None,
    profile: ProfileOption = None,
) -> None:
    """Compute topic edges, per-topic aggregates and the map layout from the shipped tags.

    Reads the tags of the method in config/tagger.yaml, writes core_topic, core_topic_edge (the
    backbone and the three lateral types) and the agg_* tables. Idempotent. Running
    `taxonomy load` afterwards replaces core_topic_edge with the backbone only; run this again.
    """
    if ctx.invoked_subcommand is not None:
        return
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    cfg = load_config(config or CONFIG_FILE)
    tagger_cfg = load_tagger_config()
    if not settings.paths.warehouse_db.exists():
        typer.echo("error: no warehouse; run the earlier stages first", err=True)
        raise typer.Exit(1)
    con = connect(settings.paths)
    try:
        with run_log(con, "aggregate") as run:
            try:
                result = stage.run(con, settings.paths, cfg, tagger_cfg, limit)
            except MissingInput as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(1) from None
            run.counts.update({k: str(v) for k, v in result.counts.items()})
    finally:
        con.close()
    typer.echo(
        f"{result.counts['works']} works: {result.counts['tagged']} tagged, "
        f"{result.counts['low_confidence']} low-confidence, {result.counts['untagged']} untagged"
    )
    for kind in (edge_mod.RELATED, edge_mod.BUILDS_ON, edge_mod.SHARED_COMMUNITY):
        typer.echo(f"  {kind}: {result.counts[f'edges_{kind}']} edges")
