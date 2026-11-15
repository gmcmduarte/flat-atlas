"""Command-line entry point: ``flatatlas``.

Each pipeline stage owns one command group; later sessions register their commands on it.
Names in ``PLAIN_COMMANDS`` are single commands instead of groups.
"""

from typing import Annotated

import typer
import yaml

from flatatlas import __version__
from flatatlas.log import setup_logging
from flatatlas.settings import load_settings
from flatatlas.status import render_status
from flatatlas.venues import (
    VenueConfigError,
    load_venue_facts,
    load_venues,
    profile_problems,
)

COMMAND_GROUPS: dict[str, str] = {
    "harvest": "Fetch raw responses from the sources into the local cache.",
    "parse": "Parse cached raw responses into warehouse tables.",
    "resolve": "Resolve venues, works and authors across sources.",
    "scope": "Decide which works belong to the field.",
    "embed": "Fetch or compute paper embeddings.",
    "taxonomy": "Propose and check the topic DAG.",
    "tag": "Assign topics to works.",
    "evaluate": "Run the automatic quality checks.",
    "aggregate": "Compute per-topic, per-venue and per-author aggregates.",
    "release": "Build and inspect versioned releases.",
    "export": "Export a release to the static site or the serving database.",
    "status": "Show what has been harvested and built so far.",
    "venues": "Inspect and validate the venue registry.",
}

PLAIN_COMMANDS = {"status"}

app = typer.Typer(
    name="flatatlas",
    help="The FLAT Atlas pipeline.",
    no_args_is_help=True,
    add_completion=False,
)

# One sub-app per group. Stage modules add commands with ``@groups["harvest"].command()``.
groups: dict[str, typer.Typer] = {
    name: typer.Typer(name=name, help=help_text, no_args_is_help=True)
    for name, help_text in COMMAND_GROUPS.items()
    if name not in PLAIN_COMMANDS
}
for _group in groups.values():
    app.add_typer(_group)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"flatatlas {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_show_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """The FLAT Atlas pipeline."""


@app.command("status", help=COMMAND_GROUPS["status"])
def status(
    profile: Annotated[
        str | None, typer.Option(help="Profile name (default: FLATATLAS_PROFILE or pilot).")
    ] = None,
) -> None:
    settings = load_settings(profile=profile)
    setup_logging(None)
    typer.echo(render_status(settings))


@groups["venues"].command("check")
def venues_check() -> None:
    """Validate config/venues.yaml and config/venue_facts.yaml."""
    try:
        registry = load_venues()
        facts = load_venue_facts(registry=registry)
        problems = profile_problems(registry)
        if problems:
            raise VenueConfigError(problems)
    except VenueConfigError as exc:
        for problem in exc.problems:
            typer.echo(f"error: {problem}", err=True)
        raise typer.Exit(1) from None
    n_facts = sum(len(years) for years in facts.venues.values())
    typer.echo(f"OK: {len(registry)} venues, {n_facts} venue-year fact entries")
    for venue_id, missing in registry.unverified():
        typer.echo(f"warning: {venue_id}: not verified against {', '.join(missing)}")


@groups["venues"].command("show")
def venues_show(venue_id: Annotated[str, typer.Argument(help="Venue id, e.g. dlt")]) -> None:
    """Print one venue entry, its predecessors and what is known about its editions."""
    try:
        registry = load_venues()
        venue = registry.get(venue_id)
    except VenueConfigError as exc:
        for problem in exc.problems:
            typer.echo(f"error: {problem}", err=True)
        raise typer.Exit(1) from None
    except KeyError as exc:
        typer.echo(f"error: {exc.args[0]}; known venues: {', '.join(registry.ids())}", err=True)
        raise typer.Exit(1) from None
    typer.echo(yaml.safe_dump(venue.model_dump(mode="json"), sort_keys=False, allow_unicode=True))
    predecessors = registry.predecessors(venue_id)
    typer.echo(f"predecessors: {', '.join(predecessors) if predecessors else '(none)'}")
    # The DBLP edition count is not wired up yet: DBLP serves a bot challenge to automated
    # clients (docs/notes/venues-pilot.md), so there is nothing verified to count against.
    typer.echo("DBLP editions: not checked (DBLP access pending, see docs/notes/venues-pilot.md)")
