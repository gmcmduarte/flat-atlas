"""The ``flatatlas taxonomy ...`` commands. ``cli.py`` registers them on the ``taxonomy`` group."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import duckdb
import typer

from flatatlas.db import connect, run_log
from flatatlas.log import setup_logging
from flatatlas.settings import load_settings
from flatatlas.taxonomy import check as tcheck
from flatatlas.taxonomy import load as tload

ProfileOption = Annotated[
    str | None, typer.Option(help="Profile name (default: FLATATLAS_PROFILE or pilot).")
]
TopicsOption = Annotated[
    Path | None,
    typer.Option(
        "--topics", help="Topics file (default: taxonomy/topics.yaml; may be a proposal)."
    ),
]
GoldOption = Annotated[
    Path | None, typer.Option("--gold", help="Labelled set (default: taxonomy/gold.yaml).")
]


def _fail(problems: list[str]) -> typer.Exit:
    for problem in problems:
        typer.echo(f"error: {problem}", err=True)
    return typer.Exit(1)


def _read_only(settings) -> duckdb.DuckDBPyConnection | None:
    if not settings.paths.warehouse_db.exists():
        return None
    try:
        return connect(settings.paths, read_only=True)
    except duckdb.Error:
        return None


def check(
    topics: TopicsOption = None,
    gold: GoldOption = None,
    allow_reviewed_edits: Annotated[
        bool, typer.Option(help="Allow changes to entries with reviewed: true (against git HEAD).")
    ] = False,
    profile: ProfileOption = None,
) -> None:
    """Validate the topic DAG and the labelled set (no network, nothing is written)."""
    settings = load_settings(profile=profile)
    topics_path = topics or tcheck.TOPICS_FILE
    gold_path = gold or tcheck.GOLD_FILE
    problems: list[str] = []

    topics_file = None
    if topics_path.exists():
        try:
            topics_file = tcheck.load_topics(topics_path)
            head_text = tcheck.git_head_text(topics_path)
            head = tcheck.parse_topics(head_text, "HEAD") if head_text else None
            problems += tcheck.check_topics(
                topics_file, head=head, allow_reviewed_edits=allow_reviewed_edits
            )
        except tcheck.TaxonomyFileError as exc:
            problems += exc.problems
        else:
            typer.echo(f"{topics_path.name}: {len(topics_file.topics)} topics")
    else:
        typer.echo(f"{topics_path.name}: not found (written by P1-06); nothing to check")

    if gold_path.exists():
        if topics_file is None:
            problems.append(f"{gold_path.name} needs a valid topics file to check labels against")
        else:
            con = _read_only(settings)
            try:
                gold_file = tcheck.load_gold(gold_path)
                head_text = tcheck.git_head_text(gold_path)
                head_gold = tcheck.parse_gold(head_text, "HEAD") if head_text else None
                problems += tcheck.check_gold(
                    gold_file,
                    topics_file,
                    resolve_work=tload.known_work_resolver(con, settings.paths),
                    head=head_gold,
                    allow_reviewed_edits=allow_reviewed_edits,
                )
                typer.echo(f"{gold_path.name}: {len(gold_file.works)} works")
            except tcheck.TaxonomyFileError as exc:
                problems += exc.problems
            finally:
                if con is not None:
                    con.close()
    else:
        typer.echo(f"{gold_path.name}: not found (written by P1-06b); nothing to check")

    if problems:
        raise _fail(problems)
    typer.echo("OK")


def load(
    topics: TopicsOption = None,
    gold: GoldOption = None,
    profile: ProfileOption = None,
) -> None:
    """Load topics.yaml into core_topic and core_topic_edge, and gold.yaml into eval_gold."""
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    topics_path = topics or tcheck.TOPICS_FILE
    gold_path = gold or tcheck.GOLD_FILE
    if not topics_path.exists():
        raise _fail([f"{topics_path} not found"])
    try:
        topics_file = tcheck.load_topics(topics_path)
        gold_file = tcheck.load_gold(gold_path) if gold_path.exists() else None
    except tcheck.TaxonomyFileError as exc:
        raise _fail(exc.problems) from None
    problems = tcheck.check_topics(topics_file)
    if problems:
        raise _fail(problems)
    con = connect(settings.paths)
    try:
        with run_log(con, "taxonomy-load") as run:
            counts = tload.write_topics(con, settings.paths, topics_file)
            if gold_file is not None:
                counts |= {
                    f"gold_{k}": v
                    for k, v in tload.write_gold(con, settings.paths, gold_file).items()
                }
            run.counts.update(counts)
    finally:
        con.close()
    typer.echo(f"loaded {counts}")


def seeds(
    ccs_file: Annotated[
        Path | None,
        typer.Option(
            "--ccs-file",
            help="The ACM CCS 2012 SKOS file, downloaded by hand from https://dl.acm.org/ccs "
            "(default: <data>/raw/seeds/acm-ccs.xml if it exists).",
        ),
    ] = None,
    profile: ProfileOption = None,
) -> None:
    """Write taxonomy/seeds/ccs.yaml and openalex_topics.yaml (no network)."""
    from flatatlas.taxonomy import config as tconfig
    from flatatlas.taxonomy import seeds as tseeds

    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    cfg = tconfig.load_config().seeds
    source = ccs_file or settings.paths.root / cfg.ccs_file
    if not source.exists():
        typer.echo(
            f"note: no CCS file at {source}; ccs.yaml not written. The ACM site refuses automated "
            "downloads: save the SKOS file from https://dl.acm.org/ccs there, then run this again.",
            err=True,
        )
        source = None
    con = _read_only(settings)
    if con is None:
        raise _fail(["no warehouse; run the parse stages first"])
    try:
        counts = tseeds.build_seeds(con, cfg, ccs_file=source)
    except tseeds.SeedError as exc:
        raise _fail([str(exc)]) from None
    finally:
        con.close()
    typer.echo(f"wrote seeds: {counts}")


def composite(
    work: Annotated[
        list[str] | None,
        typer.Option("--work", help="Show the composite text of this work ID (repeatable)."),
    ] = None,
    title: Annotated[
        list[str] | None,
        typer.Option("--title", help="Show works whose title contains this text (repeatable)."),
    ] = None,
    write: Annotated[
        bool, typer.Option("--write/--no-write", help="Rebuild local_work_text for all works.")
    ] = True,
    profile: ProfileOption = None,
) -> None:
    """Build the composite text of every work (local only) and optionally print some of them."""
    from flatatlas.text import store as text_store

    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    con = connect(settings.paths)
    try:
        with run_log(con, "composite-text") as run:
            parts = text_store.build_all(con)
            if write:
                run.counts["works"] = text_store.write_table(con, settings.paths, parts)
            run.counts["with_abstract"] = sum(p.has_abstract for p in parts)
            run.counts["with_tldr"] = sum(p.has_tldr for p in parts)
            run.counts["with_10_reference_titles"] = sum(
                len(p.reference_titles) >= 10 for p in parts
            )
            run.counts["with_no_reference_title"] = sum(not p.reference_titles for p in parts)
            counts = dict(run.counts)
    finally:
        con.close()
    typer.echo(f"composite text: {counts}")
    wanted = {w.upper() for w in work or []}
    needles = [t.casefold() for t in title or []]
    for p in parts:
        if p.work_id in wanted or any(n in p.title.casefold() for n in needles):
            typer.echo(f"\n=== {p.work_id} ({p.n_references_with_title}/{p.n_references} refs)")
            typer.echo(f"title:      {p.title}")
            typer.echo(f"venue/year: {p.venue} {p.year}")
            for i, t in enumerate(p.reference_titles, 1):
                typer.echo(f"  ref {i:>2}:   {t}")
            typer.echo(f"abstract:   {p.abstract or '(none)'}")
            typer.echo(f"tldr:       {p.tldr or '(none)'}")
            typer.echo(f"text:       {p.text}")


def mine(
    top: Annotated[int, typer.Option(help="Print this many of the best phrases.")] = 0,
    profile: ProfileOption = None,
) -> None:
    """Mine candidate phrases from the composite text (no network; about a minute)."""
    from flatatlas.taxonomy import config as tconfig
    from flatatlas.taxonomy import mine as tmine
    from flatatlas.taxonomy import stage as tstage

    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    cfg = tconfig.load_config()
    con = connect(settings.paths)
    try:
        with run_log(con, "taxonomy-mine") as run:
            parts = tstage.composite_parts(con)
            titles = tstage.background_titles(con)
            ids, matrix = tstage.work_vectors(con)
            vectors = dict(zip(ids, matrix, strict=True))
            rows = tmine.mine(
                parts,
                titles,
                cfg.mine,
                cfg.background,
                vectors=vectors,
                keywords=tstage.openalex_keywords(con),
            )
            path = tstage.write_phrases(settings.paths, rows)
            text_rows = [r for r in rows if r["source"] == "text"]
            run.counts.update(
                {
                    "works": len(parts),
                    "background_titles": len(titles),
                    "phrases": len(text_rows),
                    "keyword_candidates": len(rows) - len(text_rows),
                    "config": tconfig.config_hash(cfg),
                }
            )
            counts = dict(run.counts)
    except tstage.MissingInput as exc:
        raise _fail([str(exc)]) from None
    finally:
        con.close()
    typer.echo(f"wrote {path}: {counts}")
    for r in rows[:top] if top else []:
        typer.echo(
            f"{r['rank']:>3} {r['score']:>5.2f} spec {r['specificity']:.2f}  df {r['df']:>4}  "
            f"bg {r['df_background']:>3}  "
            f"{r['first_year'] or '-'}  {r['phrase']}"
        )


def cluster(
    top: Annotated[int, typer.Option(help="Print this many of the largest clusters.")] = 0,
    profile: ProfileOption = None,
) -> None:
    """Cluster the SPECTER2 vectors at three granularities and label the clusters."""
    from flatatlas.taxonomy import cluster as tcluster
    from flatatlas.taxonomy import config as tconfig
    from flatatlas.taxonomy import mine as tmine
    from flatatlas.taxonomy import seeds as tseeds
    from flatatlas.taxonomy import stage as tstage

    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    cfg = tconfig.load_config()
    con = connect(settings.paths)
    try:
        with run_log(con, "taxonomy-cluster") as run:
            parts = tstage.composite_parts(con)
            ids, matrix = tstage.work_vectors(con)
            phrases = tstage.read_phrases(settings.paths)
            vocabulary = {r["key"] for r in phrases if r["source"] == "text"}
            stats = tmine.merge_generic_tails(tmine.count_phrases(parts, cfg.mine))
            phrase_works = tcluster.phrase_work_weights(stats, vocabulary)
            assignments, embedding = tcluster.cluster_vectors(matrix, cfg.cluster, cfg.seed)
            rows, members = tcluster.build_cluster_rows(
                assignments,
                embedding,
                ids,
                phrase_works,
                cfg.cluster,
                openalex_primary=tstage.openalex_primary_topics(con),
                seeds=tstage.overlap_seeds(tseeds.SEEDS_DIR),
            )
            path, _ = tstage.write_clusters(settings.paths, rows, members)
            for g, labels in assignments.items():
                n = len(set(labels.tolist()) - {-1})
                run.counts[f"clusters_{g}"] = n
                run.counts[f"noise_{g}"] = int((labels == -1).sum())
            run.counts["config"] = tconfig.config_hash(cfg)
            counts = dict(run.counts)
    except tstage.MissingInput as exc:
        raise _fail([str(exc)]) from None
    except RuntimeError as exc:
        raise _fail([str(exc)]) from None
    finally:
        con.close()
    typer.echo(f"wrote {path}: {counts}")
    shown = sorted(rows, key=lambda r: (-r["size"], r["cluster_id"]))[:top] if top else []
    for r in shown:
        typer.echo(f"{r['cluster_id']:<9} {r['size']:>4}  {r['label']}")


def propose(
    version: Annotated[int, typer.Option(help="Proposal number: writes proposals/v<N>.yaml.")] = 1,
    out_dir: Annotated[
        Path | None, typer.Option(help="Where proposals go (default: taxonomy/proposals).")
    ] = None,
    review: Annotated[
        Path | None,
        typer.Option(help="Review document (default: docs/notes/taxonomy-review-v<N>.md)."),
    ] = None,
    profile: ProfileOption = None,
) -> None:
    """Combine seeds, mined phrases and clusters into a proposed topic DAG with evidence."""
    import yaml

    from flatatlas.db import write_text_atomic
    from flatatlas.settings import PROJECT_ROOT
    from flatatlas.taxonomy import config as tconfig
    from flatatlas.taxonomy import propose as tpropose
    from flatatlas.taxonomy import review as treview
    from flatatlas.taxonomy import seeds as tseeds
    from flatatlas.taxonomy import stage as tstage
    from flatatlas.taxonomy.mine import count_phrases, merge_generic_tails

    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    cfg = tconfig.load_config()
    con = connect(settings.paths)
    try:
        with run_log(con, "taxonomy-propose") as run:
            parts = tstage.composite_parts(con)
            phrases = tstage.read_phrases(settings.paths)
            clusters = tstage.read_table(
                settings.paths, tstage.CLUSTERS_FILE, "run `flatatlas taxonomy cluster` first"
            )
            members = tstage.read_table(
                settings.paths, tstage.MEMBERS_FILE, "run `flatatlas taxonomy cluster` first"
            )
            inputs = tpropose.Inputs(
                parts=parts,
                phrase_rows=phrases,
                stats=merge_generic_tails(count_phrases(parts, cfg.mine)),
                clusters=clusters,
                members=members,
                citations=tstage.citation_pairs(con),
                cited_by=tstage.cited_by_in_corpus(con),
                openalex_primary=tstage.openalex_primary_topic_ids(con),
                seeds=tstage.seeds_with_structure(tseeds.SEEDS_DIR),
                taxonomy_version=version,
                config_hash=tconfig.config_hash(cfg),
            )
            result = tpropose.propose(inputs, cfg.propose)
            target = (out_dir or PROJECT_ROOT / "taxonomy" / "proposals") / f"v{version}.yaml"
            body = yaml.safe_dump(
                result.file.model_dump(mode="json", exclude_none=True),
                sort_keys=False,
                allow_unicode=True,
                width=100,
            )
            header = (
                f"# Proposal v{version} written by `flatatlas taxonomy propose` "
                f"(settings {inputs.config_hash}).\n"
                "# Not the taxonomy: topics.yaml is drafted from this and reviewed (P1-06).\n"
            )
            write_text_atomic(target, header + body)
            doc = review or PROJECT_ROOT / "docs" / "notes" / f"taxonomy-review-v{version}.md"
            write_text_atomic(
                doc,
                treview.render(result, parts, version=version, config_hash=inputs.config_hash),
            )
            run.counts.update({k: v for k, v in result.stats.items() if not isinstance(v, dict)})
            counts = dict(run.counts)
    except tstage.MissingInput as exc:
        raise _fail([str(exc)]) from None
    finally:
        con.close()
    typer.echo(f"wrote {target} and {doc}: {counts}; levels {result.stats['levels']}")
    if result.problems:
        raise _fail(result.problems)
