"""Command-line entry point: ``flatatlas``.

Each pipeline stage owns one command group; later sessions register their commands on it.
Names in ``PLAIN_COMMANDS`` are single commands instead of groups.
"""

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml

from flatatlas import __version__
from flatatlas import coverage as coverage_report
from flatatlas.db import connect, run_log, write_text_atomic
from flatatlas.dblp_dump import (
    DTD_FILE,
    DUMP_FILE,
    INDEX_FILE,
    DumpError,
    build_stream_index,
    edition_summary,
    read_index,
    verify_checksum,
    write_index,
)
from flatatlas.embed import stage as embed_stage
from flatatlas.embed import store as embed_store
from flatatlas.http import BudgetExhausted, SourceClient, SourceError
from flatatlas.log import setup_logging
from flatatlas.settings import PROJECT_ROOT, load_settings
from flatatlas.sources import crossref as crossref_src
from flatatlas.sources import dblp as dblp_parse
from flatatlas.sources import openalex as openalex_src
from flatatlas.sources import s2 as s2_src
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
# ``embed`` runs when called without a sub-command, so it must not print its help instead.
groups: dict[str, typer.Typer] = {
    name: typer.Typer(name=name, help=help_text, no_args_is_help=name != "embed")
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
    typer.echo(_dblp_line(venue, load_settings().paths.raw / "dblp-dump" / INDEX_FILE))


def _dblp_line(venue, index_path) -> str:
    index = read_index(index_path)
    if index is None or not venue.dblp_stream:
        why = "no dblp_stream" if not venue.dblp_stream else "no index yet"
        return f"DBLP editions: unknown ({why}; run `flatatlas venues scan-dump`)"
    summary = edition_summary(
        index, venue.dblp_stream, first_year=venue.first_year, last_year=venue.last_year
    )
    if summary is None:
        return (
            f"DBLP editions: unknown (stream {venue.dblp_stream} is not in the index; "
            "run `flatatlas venues scan-dump`)"
        )
    span = f"{summary['first_year']} to {summary['last_year']}"
    gaps = (
        f"; no edition in {', '.join(map(str, summary['missing_years']))}"
        if summary["missing_years"]
        else ""
    )
    return (
        f"DBLP editions: {summary['n_editions']} ({span}; {summary['n_with_proceedings_record']} "
        f"with a proceedings record; {summary['n_papers']} papers{gaps}) "
        f"[stream {venue.dblp_stream}, dump {index['dump_md5'][:8]}, indexed {index['built_at']}]"
    )


@groups["venues"].command("scan-dump")
def venues_scan_dump(
    dump_dir: Annotated[
        Path | None,
        typer.Option(help="Folder with dblp.xml.gz and dblp.dtd (default: <data>/raw/dblp-dump)."),
    ] = None,
) -> None:
    """Index the DBLP dump for every venue stream (about two minutes, no network)."""
    settings = load_settings()
    setup_logging(None)
    folder = dump_dir or settings.paths.raw / "dblp-dump"
    dump, dtd = folder / DUMP_FILE, folder / DTD_FILE
    for needed in (dump, dtd):
        if not needed.exists():
            typer.echo(f"error: {needed} not found; see docs/notes/venues-pilot.md", err=True)
            raise typer.Exit(1)
    streams = sorted({v.dblp_stream for v in load_venues() if v.dblp_stream})
    try:
        md5 = verify_checksum(dump)
        has_md5_file = dump.with_name(dump.name + ".md5").exists()
        checked = "matches the .md5 file" if has_md5_file else "no .md5 file to compare"
        typer.echo(f"{dump.name}: MD5 {md5} ({checked})")
        typer.echo(f"streams: {', '.join(streams)}")
        index = build_stream_index(
            dump,
            dtd,
            streams,
            progress=lambda n: (
                typer.echo(f"  {n:,} records read", err=True) if n % 2_000_000 == 0 else None
            ),
        )
    except DumpError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    path = write_index(index, folder / INDEX_FILE)
    typer.echo(f"wrote {path}")
    for stream, info in index["streams"].items():
        summary = edition_summary(index, stream)
        typer.echo(
            f"  {stream}: {summary['n_editions']} editions, {info['n_records']} records, "
            f"{summary['first_year']} to {summary['last_year']}"
        )


@groups["parse"].command("dblp")
def parse_dblp(
    venue: Annotated[
        str | None, typer.Option(help="Parse one venue (and its predecessors), e.g. dlt.")
    ] = None,
    dump_dir: Annotated[
        Path | None,
        typer.Option(help="Folder with dblp.xml.gz and dblp.dtd (default: <data>/raw/dblp-dump)."),
    ] = None,
    profile: Annotated[
        str | None, typer.Option(help="Profile name (default: FLATATLAS_PROFILE or pilot).")
    ] = None,
) -> None:
    """Parse the DBLP dump into the stg_dblp_* tables (no network; a few minutes)."""
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    try:
        registry = load_venues()
        venues = dblp_parse.select_venues(registry, settings.profile.active_venues, venue)
    except VenueConfigError as exc:
        for problem in exc.problems:
            typer.echo(f"error: {problem}", err=True)
        raise typer.Exit(1) from None
    except (KeyError, ValueError) as exc:
        typer.echo(f"error: {exc.args[0]}", err=True)
        raise typer.Exit(1) from None

    folder = dump_dir or settings.paths.raw / "dblp-dump"
    dump, dtd = folder / DUMP_FILE, folder / DTD_FILE
    for needed in (dump, dtd):
        if not needed.exists():
            typer.echo(f"error: {needed} not found; see docs/notes/venues-pilot.md", err=True)
            raise typer.Exit(1)
    typer.echo(f"venues: {', '.join(v.id for v in venues)}")

    con = connect(settings.paths)
    try:
        with run_log(con, "parse-dblp") as run:
            md5 = verify_checksum(dump)
            facts = dblp_parse.dump_facts(dump, md5)
            run.counts.update(facts)
            run.counts["venues"] = ",".join(v.id for v in venues)
            typer.echo(f"{dump.name}: MD5 {md5} (file date {facts['dump_file_date']})")
            parsed = dblp_parse.parse_dump(
                dump,
                dtd,
                venues,
                dblp_parse.load_rules(),
                progress=lambda n: typer.echo(f"  {n:,} records read", err=True),
            )
            run.counts.update(parsed.stats)
            run.counts["newest_mdate"] = parsed.notes["newest_mdate"]
            dblp_parse.write_tables(con, settings.paths, parsed)
    except DumpError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    finally:
        con.close()

    index = read_index(folder / INDEX_FILE)
    stale = index is not None and index.get("dump_md5") != md5
    checks = dblp_parse.compare_with_index(parsed, None if stale else index, venues)
    typer.echo(_parse_report(parsed, checks, stale, index is None))


def _parse_report(parsed, checks: list[dict], stale: bool, no_index: bool) -> str:
    s = parsed.stats
    lines = [
        "",
        f"editions {s['editions']}, papers {s['papers']} "
        f"({s['papers_front_matter']} flagged front matter), "
        f"authorships {s['authorships']}, authors {s['authors']}",
        f"left out: {s['papers_excluded']} papers of {s['editions_excluded']} excluded edition(s); "
        f"{s['papers_unassigned']} papers and {s['editions_unassigned']} editions outside every "
        f"venue's year range; {s['papers_without_edition']} papers without crossref",
        f"names without a PID: {s['names_without_pid']} "
        f"({s['authorships_without_pid']} authorships); ambiguous names: {s['names_ambiguous']}; "
        f"ORCID conflicts: {s['orcid_conflicts']}; "
        f"second pass over the dump: {'yes' if parsed.notes['second_pass'] else 'no'}",
    ]
    if stale or no_index:
        why = "was built from another dump" if stale else "does not exist"
        lines.append(f"count check skipped: stream_index.json {why} (run `venues scan-dump`)")
    else:
        differs = [c for c in checks if c["status"] == "differs"]
        n_ok = sum(c["status"] == "ok" for c in checks)
        n_other = sum(c["status"] == "not indexed" for c in checks)
        lines.append(
            f"count check against the stream index: {n_ok} editions match, "
            f"{len(differs)} differ, {n_other} not in the index (extra editions)"
        )
        lines.extend(
            f"  DIFFERS {c['edition_key']} ({c['venue_id']} {c['year']}): "
            f"parsed {c['parsed']}, index {c['indexed']}"
            for c in differs
        )
    lines.append("DOI share per venue and decade (front matter left out):")
    lines.extend(
        f"  {r['venue_id']:<7} {r['decade']}s  {r['with_doi']:>4}/{r['papers']:<4} "
        f"{r['share']:>5.0%}"
        for r in dblp_parse.doi_share(parsed)
    )
    return "\n".join(lines)


# -- P1-02: OpenAlex, Crossref, coverage ---------------------------------------------------------

ProfileOption = Annotated[
    str | None, typer.Option(help="Profile name (default: FLATATLAS_PROFILE or pilot).")
]
VenueOption = Annotated[
    str | None, typer.Option(help="Only this venue (and its predecessors), e.g. dlt.")
]


def _venue_ids(settings, venue: str | None) -> list[str]:
    try:
        registry = load_venues()
        venues = dblp_parse.select_venues(registry, settings.profile.active_venues, venue)
    except VenueConfigError as exc:
        for problem in exc.problems:
            typer.echo(f"error: {problem}", err=True)
        raise typer.Exit(1) from None
    except (KeyError, ValueError) as exc:
        typer.echo(f"error: {exc.args[0]}", err=True)
        raise typer.Exit(1) from None
    return [v.id for v in venues]


def _require_tables(con, *names: str, hint: str) -> None:
    have = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    missing = [n for n in names if n not in have]
    if missing:
        typer.echo(f"error: missing table(s) {', '.join(missing)}; {hint}", err=True)
        raise typer.Exit(1)


def _spend_line(client: SourceClient) -> str:
    budget = client.cfg.daily_budget_usd
    spent = client.ledger.spent_today_usd()
    return f"spent today (UTC): ${spent:.4f}" + (f" of ${budget:.2f}" if budget else "")


@groups["harvest"].command("openalex")
def harvest_openalex(
    limit: Annotated[
        int | None, typer.Option(help="Only this many papers (a hash-ordered sample).")
    ] = None,
    venue: VenueOption = None,
    max_title_searches: Annotated[
        int,
        typer.Option(help="Most title searches for papers without a DOI (USD 0.001 each)."),
    ] = openalex_src.DEFAULT_MAX_TITLE_SEARCHES,
    restart: Annotated[bool, typer.Option(help="Ignore a finished job state.")] = False,
    profile: ProfileOption = None,
) -> None:
    """Fetch OpenAlex works for the DBLP papers: by DOI in batches, then capped title searches.

    Resumable: stop it any time and run the same command again. Run `flatatlas parse openalex`
    afterwards.
    """
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    venue_ids = _venue_ids(settings, venue)
    con = connect(settings.paths)
    client = SourceClient("openalex", settings)
    try:
        _require_tables(con, "stg_dblp_paper", hint="run `flatatlas parse dblp` first")
        papers = openalex_src.load_papers(con, venue_ids=venue_ids, limit=limit)
        n_doi = sum(1 for p in papers if p.doi)
        typer.echo(
            f"venues: {', '.join(venue_ids)}; {len(papers)} papers ({n_doi} with a DOI, "
            f"{len(papers) - n_doi} without); {_spend_line(client)}"
        )
        with run_log(con, "harvest-openalex") as run:
            try:
                stats = openalex_src.harvest(
                    con,
                    client,
                    papers,
                    max_title_searches=max_title_searches,
                    restart=restart,
                    on_progress=typer.echo,
                )
            finally:
                run.counts["spent_today_usd"] = round(client.ledger.spent_today_usd(), 6)
            run.counts.update(stats.as_counts())
        typer.echo(f"done: {stats.as_counts()}")
        if stats.papers_without_search:
            typer.echo(
                f"note: {stats.papers_without_search} papers without a usable DOI were not "
                f"searched (cap {max_title_searches}); raise --max-title-searches to cover them"
            )
    except BudgetExhausted as exc:
        typer.echo(f"stopped: {exc} Progress is saved; run the same command again.", err=True)
        raise typer.Exit(3) from None
    except SourceError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    finally:
        typer.echo(_spend_line(client))
        client.close()
        con.close()


@groups["parse"].command("openalex")
def parse_openalex(
    venue: VenueOption = None,
    show: Annotated[
        int, typer.Option(help="Also print this many random matched papers, enriched.")
    ] = 0,
    profile: ProfileOption = None,
) -> None:
    """Parse cached OpenAlex answers into the stg_openalex_* tables (no network)."""
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    venue_ids = _venue_ids(settings, venue)
    con = connect(settings.paths)
    client = SourceClient("openalex", settings)
    try:
        _require_tables(con, "stg_dblp_paper", hint="run `flatatlas parse dblp` first")
        papers = openalex_src.load_papers(con, venue_ids=venue_ids)
        with run_log(con, "parse-openalex") as run:
            parsed = openalex_src.parse_openalex(client, papers)
            run.counts.update({k: int(v) for k, v in parsed.stats.items()})
            run.counts["papers"] = len(papers)
            openalex_src.write_tables(con, settings.paths, parsed)
    finally:
        client.close()
        con.close()
    s = parsed.stats
    typer.echo(
        f"{len(papers)} papers: {s['fetched']} fetched, {s['matched']} matched "
        f"({s['lookup_doi']} by DOI lookup, {s['lookup_title']} by title lookup, "
        f"{s['lookup_none']} not searchable)"
    )
    typer.echo(
        f"works {s['works']}, references {s['references']}, "
        f"reference candidates {s['reference_candidates']}, abstracts {s['abstracts']}"
    )
    for row in openalex_src.sample_rows(parsed, show) if show else []:
        typer.echo(json.dumps(row, ensure_ascii=False, indent=1))


@groups["harvest"].command("crossref")
def harvest_crossref(
    limit: Annotated[int | None, typer.Option(help="Only this many DOIs (a sample).")] = None,
    venue: VenueOption = None,
    restart: Annotated[bool, typer.Option(help="Ignore a finished job state.")] = False,
    profile: ProfileOption = None,
) -> None:
    """Fetch Crossref records for DOIs OpenAlex lacks or covers only partly.

    Needs `flatatlas parse openalex` first (it decides which DOIs are needed).
    """
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    venue_ids = _venue_ids(settings, venue)
    con = connect(settings.paths)
    client = SourceClient("crossref", settings)
    try:
        _require_tables(
            con,
            "stg_dblp_paper",
            "stg_openalex_lookup",
            "stg_openalex_work",
            hint="run `flatatlas parse dblp` and `flatatlas parse openalex` first",
        )
        dois = crossref_src.dois_needing_crossref(con, venue_ids=venue_ids, limit=limit)
        typer.echo(f"{len(dois)} DOIs to ask Crossref (missing in OpenAlex or lacking fields)")
        with run_log(con, "harvest-crossref") as run:
            stats = crossref_src.harvest(con, client, dois, restart=restart, on_progress=typer.echo)
            run.counts.update(stats.as_counts())
        typer.echo(f"done: {stats.as_counts()}")
    except SourceError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    finally:
        client.close()
        con.close()


@groups["parse"].command("crossref")
def parse_crossref(venue: VenueOption = None, profile: ProfileOption = None) -> None:
    """Parse cached Crossref answers into stg_crossref_work and local_abstract (no network)."""
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    venue_ids = _venue_ids(settings, venue)
    con = connect(settings.paths)
    client = SourceClient("crossref", settings)
    try:
        _require_tables(con, "stg_dblp_paper", hint="run `flatatlas parse dblp` first")
        papers = openalex_src.load_papers(con, venue_ids=venue_ids)
        pairs = [(p.dblp_key, p.doi) for p in papers if p.doi]
        with run_log(con, "parse-crossref") as run:
            parsed = crossref_src.parse_crossref(client, pairs)
            run.counts.update({k: int(v) for k, v in parsed.stats.items()})
            crossref_src.write_tables(con, settings.paths, parsed)
    finally:
        client.close()
        con.close()
    s = parsed.stats
    typer.echo(
        f"{len(pairs)} papers with a DOI: {s['found']} DOIs found, {s['not_found']} not found, "
        f"{s['not_fetched']} not fetched, {s['skipped_not_crossref']} skipped (not Crossref); "
        f"abstracts {s['abstracts']}"
    )


@groups["harvest"].command("s2")
def harvest_s2(
    limit: Annotated[
        int | None, typer.Option(help="Only this many papers (the same hash-ordered sample).")
    ] = None,
    venue: VenueOption = None,
    max_title_matches: Annotated[
        int,
        typer.Option(help="Most title matches for papers S2 does not return by DOI (1 call each)."),
    ] = s2_src.DEFAULT_MAX_TITLE_MATCHES,
    restart: Annotated[bool, typer.Option(help="Ignore a finished job state.")] = False,
    profile: ProfileOption = None,
) -> None:
    """Fetch Semantic Scholar records for the DBLP papers: DOI batches, then title matches.

    Resumable: stop it any time and run the same command again. Run `flatatlas parse s2`
    afterwards. Title matches cost one request each at 1 request/s.
    """
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    venue_ids = _venue_ids(settings, venue)
    con = connect(settings.paths)
    client = SourceClient("semanticscholar", settings)
    try:
        _require_tables(con, "stg_dblp_paper", hint="run `flatatlas parse dblp` first")
        papers = openalex_src.load_papers(con, venue_ids=venue_ids, limit=limit)
        n_doi = sum(1 for p in papers if p.doi)
        has_key = bool(settings.secret_for("semanticscholar"))
        key = "set" if has_key else "NOT set (shared, unreliable pool)"
        typer.echo(
            f"venues: {', '.join(venue_ids)}; {len(papers)} papers ({n_doi} with a DOI, "
            f"{len(papers) - n_doi} without); S2 key {key}"
        )
        with run_log(con, "harvest-s2") as run:
            stats = s2_src.harvest(
                con,
                client,
                papers,
                max_title_matches=max_title_matches,
                restart=restart,
                on_progress=typer.echo,
            )
            run.counts.update(stats.as_counts())
        typer.echo(f"done: {stats.as_counts()}")
        if stats.papers_not_matched_by_cap:
            typer.echo(
                f"note: {stats.papers_not_matched_by_cap} papers were not title-matched (cap "
                f"{max_title_matches}); raise --max-title-matches to cover them"
            )
    except SourceError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    finally:
        client.close()
        con.close()


@groups["parse"].command("s2")
def parse_s2(venue: VenueOption = None, profile: ProfileOption = None) -> None:
    """Parse cached S2 answers into stg_s2_*, local_abstract and local_embedding (no network)."""
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    venue_ids = _venue_ids(settings, venue)
    con = connect(settings.paths)
    client = SourceClient("semanticscholar", settings)
    try:
        _require_tables(con, "stg_dblp_paper", hint="run `flatatlas parse dblp` first")
        papers = openalex_src.load_papers(con, venue_ids=venue_ids)
        with run_log(con, "parse-s2") as run:
            parsed = s2_src.parse_s2(client, papers)
            run.counts.update({k: int(v) for k, v in parsed.stats.items()})
            s2_src.write_tables(con, settings.paths, parsed)
    finally:
        client.close()
        con.close()
    s = parsed.stats
    typer.echo(
        f"{s['papers']} papers: {s['matched']} matched ({s['matched_doi']} by DOI, "
        f"{s['matched_title']} by title), {s['not_found']} not found, "
        f"{s['not_fetched']} not fetched"
    )
    typer.echo(
        f"S2 papers {s['s2_papers']}, references {s['references']}, abstracts {s['abstracts']}, "
        f"S2 vectors {s['embeddings']}"
    )


@groups["embed"].callback(invoke_without_command=True)
def embed_run(
    ctx: typer.Context,
    limit: Annotated[
        int | None,
        typer.Option(help="Embed at most this many papers locally (a hash-ordered sample)."),
    ] = None,
    venue: VenueOption = None,
    device: Annotated[
        str | None, typer.Option(help="mps | cpu | cuda (default: the profile's embedding_device).")
    ] = None,
    profile: ProfileOption = None,
) -> None:
    """Give every paper one SPECTER2 vector: S2's (from `parse s2`), else computed locally.

    Needs `uv sync --extra ml` (torch) and `flatatlas parse s2` first. Resumable: finished
    batches are cached, so a stopped run continues where it was.
    """
    if ctx.invoked_subcommand is not None:
        return
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    venue_ids = _venue_ids(settings, venue)
    con = connect(settings.paths)
    try:
        _require_tables(
            con, "stg_dblp_paper", "stg_s2_lookup", hint="run `parse dblp` and `parse s2` first"
        )
        papers = embed_stage.load_paper_texts(con, venue_ids)
        missing = embed_stage.papers_without_s2_vector(con, papers)
        typer.echo(
            f"{len(papers)} papers; {len(papers) - len(missing)} have an S2 vector; "
            f"{len(missing)} need a local one"
        )
        if not missing:
            typer.echo("nothing to compute")
        dev = device or settings.profile.embedding_device
        encoder = None
        if missing:
            from flatatlas.embed.specter2 import MissingMlExtra, load_encoder

            typer.echo(f"loading SPECTER2 on {dev} (the first run downloads the model) ...")
            try:
                encoder = load_encoder(dev)
            except MissingMlExtra as exc:
                typer.echo(f"error: {exc}", err=True)
                raise typer.Exit(1) from None
            typer.echo(f"device in use: {encoder.device}")
        with run_log(con, "embed") as run:
            result = (
                embed_stage.run_embed(
                    con,
                    settings.paths,
                    encoder,
                    papers,
                    limit=limit,
                    batch_size=settings.profile.batch_sizes.get("embed", 32),
                    on_progress=typer.echo,
                )
                if encoder
                else None
            )
            cov = embed_store.coverage(con, [p.dblp_key for p in papers])
            run.counts.update({k: v for k, v in cov.items() if isinstance(v, int)})
            if result:
                run.counts.update(
                    local_computed=result.stats.computed,
                    local_from_cache=result.stats.from_cache,
                    local_seconds=round(result.stats.seconds, 1),
                )
    finally:
        con.close()
    if result:
        st = result.stats
        typer.echo(
            f"local: {result.done} of {result.wanted} papers embedded ({result.kinds}); "
            f"{st.computed} computed, {st.from_cache} from cache, {st.per_second:.1f} texts/s"
        )
    typer.echo(
        f"vectors: {cov['with_vector']} of {cov['papers']} papers {cov['by_source']}; "
        f"missing {cov['missing']}; papers with more than one vector: {cov['duplicated']}"
    )


@groups["embed"].command("compare")
def embed_compare(
    sample: Annotated[int, typer.Option(help="Papers with an S2 vector to embed locally.")] = 50,
    device: Annotated[
        str | None, typer.Option(help="mps | cpu | cuda (default: the profile's embedding_device).")
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(help="Report file (default: reports/embedding-compare-<profile>.md)."),
    ] = None,
    profile: ProfileOption = None,
) -> None:
    """Embed papers that have an S2 vector with the local model and report the cosine."""
    from flatatlas.embed.specter2 import MissingMlExtra, load_encoder

    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    con = connect(settings.paths)
    try:
        _require_tables(con, "stg_dblp_paper", "stg_s2_lookup", hint="run `parse s2` first")
        papers = embed_stage.load_paper_texts(con)
        dev = device or settings.profile.embedding_device
        try:
            encoder = load_encoder(dev)
        except MissingMlExtra as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        typer.echo(f"device in use: {encoder.device}")
        comparison = embed_stage.compare_with_s2(
            con,
            encoder,
            papers,
            n=sample,
            batch_size=settings.profile.batch_sizes.get("embed", 32),
            device=encoder.device,
            on_progress=typer.echo,
        )
    finally:
        con.close()
    text = embed_stage.render_comparison(comparison, profile=settings.profile.name)
    path = out or PROJECT_ROOT / "reports" / f"embedding-compare-{settings.profile.name}.md"
    write_text_atomic(path, text)
    typer.echo(text)
    typer.echo(f"wrote {path}")


@groups["evaluate"].command("coverage")
def evaluate_coverage(
    out: Annotated[
        Path | None,
        typer.Option(help="Report file (default: reports/coverage-<profile>.md in the repo)."),
    ] = None,
    profile: ProfileOption = None,
) -> None:
    """Write the coverage report: matches, abstracts, references and affiliations per venue."""
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    con = connect(settings.paths)
    try:
        cov = coverage_report.compute(con)
    except LookupError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    finally:
        con.close()
    path = out or PROJECT_ROOT / "reports" / f"coverage-{settings.profile.name}.md"
    write_text_atomic(path, coverage_report.render(cov, profile=settings.profile.name))
    typer.echo(f"wrote {path}")
    t = cov.total
    typer.echo(
        f"papers {t['papers']}; matched {t['matched']}; DOI match "
        f"{t['doi_matched']}/{t['doi_fetched']}; abstracts {t['abs_any']}; refs {t['refs_any']}"
    )
