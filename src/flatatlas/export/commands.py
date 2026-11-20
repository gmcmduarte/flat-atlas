"""``flatatlas export static | types`` (P1-09); ``cli.py`` registers them on its group."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from flatatlas.export import static, typegen
from flatatlas.log import setup_logging
from flatatlas.settings import PROJECT_ROOT, load_settings

ProfileOption = Annotated[
    str | None, typer.Option(help="Profile name (default: FLATATLAS_PROFILE or pilot).")
]
DEFAULT_OUT = PROJECT_ROOT / "web" / "static" / "data"


def static_cmd(
    release: Annotated[
        Path | None, typer.Option(help="A release folder (default: the latest one).")
    ] = None,
    out: Annotated[
        Path | None, typer.Option(help="Where the site reads its data (default: web/static/data).")
    ] = None,
    profile: ProfileOption = None,
) -> None:
    """Write a release as the static JSON of the site and report its size (limit 30 MB)."""
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    try:
        folder = release or static.latest_release(settings.paths.releases)
        result = static.export_static(folder, out or DEFAULT_OUT)
    except static.ExportError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"{folder.name} -> {result.out}: {result.files} files, {result.bytes / 1e6:.2f} MB")
    for part, size in sorted(result.by_part.items(), key=lambda kv: -kv[1]):
        typer.echo(f"  {part:8} {size / 1e6:6.2f} MB")
    if result.bytes > static.MAX_BYTES:
        typer.echo(
            f"error: over the {static.MAX_BYTES / 1e6:.0f} MB budget of PLAN §11.2", err=True
        )
        raise typer.Exit(1)


def types_cmd(
    check: Annotated[
        bool, typer.Option("--check", help="Only check the committed files are current.")
    ] = False,
) -> None:
    """Write the JSON Schemas and web/src/lib/data/types.ts from the export models."""
    if check:
        stale = typegen.out_of_date()
        for path in stale:
            typer.echo(f"out of date: {path.relative_to(PROJECT_ROOT)}", err=True)
        if stale:
            raise typer.Exit(1)
        typer.echo("schemas and types.ts are in sync with the export models")
        return
    for path in typegen.write():
        typer.echo(f"wrote {path.relative_to(PROJECT_ROOT)}")
