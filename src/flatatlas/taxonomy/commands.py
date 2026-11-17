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
from flatatlas.venues import load_venues

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
AnchorsOption = Annotated[
    Path | None,
    typer.Option("--anchors", help="Anchor papers (default: taxonomy/anchors.yaml)."),
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
    anchors: AnchorsOption = None,
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

    # The repository's anchors and venue expectations refer to the repository's topics file;
    # a draft or proposal given with --topics is checked against them only when asked.
    repo_topics = topics_path.resolve() == tcheck.TOPICS_FILE.resolve()
    anchors_path = anchors or tcheck.ANCHORS_FILE
    if anchors is not None or repo_topics:
        problems += _check_anchors_file(anchors_path, topics_file, allow_reviewed_edits)

    if topics_file is not None and repo_topics:
        expected = {v.id: v.expected_topics for v in load_venues().venues if v.expected_topics}
        problems += tcheck.check_expected_topics(expected, topics_file)
        if expected:
            typer.echo(f"venues.yaml: expected topics of {len(expected)} venues")

    if problems:
        raise _fail(problems)
    typer.echo("OK")


def _check_anchors_file(path: Path, topics_file, allow_reviewed_edits: bool) -> list[str]:
    if not path.exists():
        typer.echo(f"{path.name}: not found; nothing to check")
        return []
    if topics_file is None:
        return [f"{path.name} needs a valid topics file to check against"]
    try:
        anchors_file = tcheck.load_anchors(path)
        head_text = tcheck.git_head_text(path)
        head = tcheck.parse_anchors(head_text, "HEAD") if head_text else None
    except tcheck.TaxonomyFileError as exc:
        return exc.problems
    typer.echo(f"{path.name}: {len(anchors_file.anchors)} anchors")
    return tcheck.check_anchors(
        anchors_file, topics_file, head=head, allow_reviewed_edits=allow_reviewed_edits
    )


def anchors(
    anchors_file: AnchorsOption = None,
    topics: TopicsOption = None,
    find: Annotated[
        bool,
        typer.Option(
            "--find",
            help="Propose identifiers for anchors that have none (DBLP dump, then OpenAlex "
            "title search); prints candidates and changes no file.",
        ),
    ] = False,
    estimate: Annotated[
        bool,
        typer.Option("--estimate", help="With --find: print the calls and the cost, then stop."),
    ] = False,
    max_searches: Annotated[
        int, typer.Option(help="With --find: at most this many OpenAlex title searches.")
    ] = 60,
    offline: Annotated[
        bool, typer.Option("--offline", help="Use cached OpenAlex answers only (no network).")
    ] = False,
    dump_dir: Annotated[
        Path | None,
        typer.Option(help="Folder with dblp.xml.gz and dblp.dtd (default: <data>/raw/dblp-dump)."),
    ] = None,
    profile: ProfileOption = None,
) -> None:
    """Verify every anchor's DOI or DBLP key and say whether it is in the corpus."""
    from flatatlas.dblp_dump import DTD_FILE, DUMP_FILE
    from flatatlas.http import SourceClient
    from flatatlas.taxonomy import anchors as tanchors

    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    path = anchors_file or tcheck.ANCHORS_FILE
    try:
        file = tcheck.load_anchors(path)
        topics_file = tcheck.load_topics(topics or tcheck.TOPICS_FILE)
    except (OSError, tcheck.TaxonomyFileError) as exc:
        problems = exc.problems if isinstance(exc, tcheck.TaxonomyFileError) else [str(exc)]
        raise _fail(problems) from None
    static = tcheck.check_anchors(file, topics_file)
    if static and not find:
        raise _fail(static)

    con = _read_only(settings)
    try:
        corpus = tanchors.load_corpus(con)
    finally:
        if con is not None:
            con.close()
    folder = dump_dir or settings.paths.raw / "dblp-dump"
    dump, dtd = folder / DUMP_FILE, folder / DTD_FILE
    client = SourceClient("openalex", settings)

    def read_dump(keys=(), titles=()):
        if not dump.exists():
            typer.echo(f"note: no DBLP dump at {dump}; DBLP keys outside the corpus stay unchecked")
            return None, {}
        typer.echo("reading the DBLP dump (about two minutes) ...")
        return tanchors.scan_dump(dump, dtd, keys=keys, titles=titles)

    if find:
        _find(file.anchors, tanchors, client, read_dump, estimate, max_searches)
        return

    keys = tanchors.needs_dump(file.anchors, corpus)
    dump_records = read_dump(keys=keys)[0] if keys else {}
    statuses = tanchors.verify(
        file.anchors,
        corpus,
        doi_lookup=lambda doi: tanchors.lookup_doi(client, doi, offline=offline),
        dump_records=dump_records,
    )
    for s in statuses:
        a = s.anchor
        where = s.work_id or "-"
        mark = "ok " if s.ok else "BAD"
        typer.echo(f"{mark} {a.id:34} {a.kind:7} {where:12} {a.topic}")
        for p in s.problems:
            typer.echo(f"      ! {p}")
        for n in s.notes:
            typer.echo(f"      note: {n}")
    n_ok = sum(s.ok for s in statuses)
    n_in = sum(s.work_id is not None for s in statuses)
    typer.echo(
        f"{len(statuses)} anchors: {n_ok} verified, {n_in} in the corpus "
        f"({sum(s.anchor.kind == 'pilot' for s in statuses)} marked pilot)"
    )
    if n_ok < len(statuses):
        raise _fail([f"{len(statuses) - n_ok} anchors could not be verified"])


def _find(anchors_list, tanchors, client, read_dump, estimate: bool, max_searches: int) -> None:
    todo = [a for a in anchors_list if a.doi is None and a.dblp is None]
    if not todo:
        typer.echo("every anchor has an identifier; nothing to find")
        return
    typer.echo(f"{len(todo)} anchors without identifiers")
    _, by_title = (None, {}) if estimate else read_dump(titles=[a.title for a in todo])
    rest = []
    for a in todo:
        cands = tanchors.candidates(a, by_title.get(tanchors.normalize_title(a.title), []))
        if cands:
            _print_candidates(a, cands)
        else:
            rest.append(a)
    searches = rest[:max_searches]
    cost = len(searches) * tanchors.SEARCH_COST_USD
    typer.echo(f"OpenAlex title searches: {len(searches)} (at most USD {cost:.3f})")
    if estimate:
        return
    for a in searches:
        cands = tanchors.candidates(a, tanchors.search_title(client, a.title, a.year))
        if cands:
            _print_candidates(a, cands)
        else:
            typer.echo(f"- {a.id}: nothing found")


def _print_candidates(anchor, cands) -> None:
    typer.echo(f"- {anchor.id}:")
    for sim, f in cands[:3]:
        typer.echo(
            f"    {sim:.2f} {f.source:9} dblp={f.dblp or '-'} doi={f.doi or '-'} "
            f"{f.year} {f.title[:80]}"
        )


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
