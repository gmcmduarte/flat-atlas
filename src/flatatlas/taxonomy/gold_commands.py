"""The ``flatatlas gold ...`` commands (P1-06b, PLAN §9.6). ``cli.py`` registers them."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from flatatlas.db import connect, run_log, write_text_atomic
from flatatlas.log import setup_logging
from flatatlas.settings import PROJECT_ROOT, load_settings
from flatatlas.taxonomy import check as tcheck
from flatatlas.taxonomy import config as tconfig
from flatatlas.taxonomy import gold as tgold

ProfileOption = Annotated[
    str | None, typer.Option(help="Profile name (default: FLATATLAS_PROFILE or pilot).")
]
DRAFT_FILE = PROJECT_ROOT / "taxonomy" / "proposals" / "gold-draft.yaml"
REPORT_FILE = PROJECT_ROOT / "docs" / "notes" / "gold-v1-report.md"
SAMPLE_NAME = "gold-sample.yaml"
BLIND_NAME = "gold-blind.md"
CONTEXT_NAME = "gold-context.md"


def _fail(problems: list[str]) -> typer.Exit:
    for problem in problems:
        typer.echo(f"error: {problem}", err=True)
    return typer.Exit(1)


def sample(
    n: Annotated[int | None, typer.Option(help="Works to sample (default: config).")] = None,
    seed: Annotated[int | None, typer.Option(help="Random seed (default: config).")] = None,
    profile: ProfileOption = None,
) -> None:
    """Draw the stratified random sample of in-scope works and choose the blind subset."""
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    cfg = tconfig.load_config().gold
    n = cfg.n if n is None else n
    seed = cfg.seed if seed is None else seed
    target = settings.paths.review / SAMPLE_NAME
    con = connect(settings.paths)
    try:
        with run_log(con, "gold-sample") as run:
            frame = tgold.sampling_frame(con)
            result = tgold.draw(
                frame, n=n, seed=seed, min_per_cell=cfg.min_per_cell, n_blind=cfg.n_blind
            )
            write_text_atomic(target, tgold.dump_sample(result))
            run.counts.update(
                {
                    "seed": seed,
                    "n": n,
                    "frame": len(frame),
                    "sampled": len(result.works),
                    "blind": len(result.blind_ids()),
                    "frame_counts": result.frame_counts,
                    "quotas": result.quotas,
                }
            )
    except tgold.GoldError as exc:
        raise _fail(exc.problems) from None
    finally:
        con.close()
    typer.echo(f"frame {len(frame)} works in {len(result.frame_counts)} cells; seed {seed}")
    typer.echo(f"{'cell':<32} {'frame':>6} {'sample':>7}")
    for cell, size in result.frame_counts.items():
        typer.echo(f"{cell:<32} {size:>6} {result.quotas.get(cell, 0):>7}")
    typer.echo(f"wrote {target}: {len(result.works)} works, {len(result.blind_ids())} blind")


def _read_sample(settings) -> tgold.Sample:
    path = settings.paths.review / SAMPLE_NAME
    if not path.exists():
        raise _fail([f"{path} not found; run `flatatlas gold sample` first"])
    return tgold.load_sample(path.read_text(encoding="utf-8"))


def sheet(
    draft: Annotated[
        Path | None, typer.Option(help="Draft file (default: taxonomy/proposals/gold-draft.yaml).")
    ] = None,
    profile: ProfileOption = None,
) -> None:
    """Write the blind sheet, the draft YAML (keeping drafted labels) and the context sheet."""
    from flatatlas.text import store as text_store

    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    the_sample = _read_sample(settings)
    topics = tcheck.load_topics()
    draft_path = draft or DRAFT_FILE
    existing = tcheck.load_gold(draft_path) if draft_path.exists() else None
    con = connect(settings.paths)
    try:
        with run_log(con, "gold-sheet") as run:
            frame = {w.work_id: w for w in tgold.sampling_frame(con)}
            missing = [wid for wid in the_sample.ids() if wid not in frame]
            if missing:
                raise _fail([f"{wid}: sampled but no longer in the frame" for wid in missing])
            parts = {p.work_id: p for p in text_store.build_all(con, work_ids=the_sample.ids())}
            draft_file = tgold.build_draft(
                the_sample, frame, taxonomy_version=topics.taxonomy_version, existing=existing
            )
            write_text_atomic(
                draft_path, tgold.render_gold_yaml(draft_file, frame, header=tgold.DRAFT_HEADER)
            )
            blind_path = settings.paths.review / BLIND_NAME
            if blind_path.exists():
                typer.echo(f"kept {blind_path} (it exists; delete it to write a fresh one)")
            else:
                write_text_atomic(
                    blind_path, tgold.render_blind_md(the_sample, frame, parts, topics)
                )
            context_path = settings.paths.review / CONTEXT_NAME
            write_text_atomic(context_path, tgold.render_context_md(the_sample, frame, parts))
            run.counts.update(
                {
                    "works": len(draft_file.works),
                    "blind": sum(w.blind for w in draft_file.works),
                    "with_labels": sum(bool(w.labels) for w in draft_file.works),
                }
            )
            counts = dict(run.counts)
    finally:
        con.close()
    typer.echo(f"wrote {draft_path}, {blind_path}, {context_path}: {counts}")


def finalise(
    draft: Annotated[
        Path | None, typer.Option(help="Reviewed draft (default: proposals/gold-draft.yaml).")
    ] = None,
    blind: Annotated[
        Path | None, typer.Option(help="Blind sheet (default: <data>/review/gold-blind.md).")
    ] = None,
    out: Annotated[Path | None, typer.Option(help="Output (default: taxonomy/gold.yaml).")] = None,
    profile: ProfileOption = None,
) -> None:
    """Write taxonomy/gold.yaml from the reviewed draft and the blind labels; refuse on problems."""
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    topics = tcheck.load_topics()
    draft_file = tcheck.load_gold(draft or DRAFT_FILE)
    blind_path = blind or settings.paths.review / BLIND_NAME
    if not blind_path.exists():
        raise _fail([f"{blind_path} not found"])
    blind_entries = tgold.parse_blind_md(blind_path.read_text(encoding="utf-8"))
    target = out or tcheck.GOLD_FILE
    existing = tcheck.load_gold(target) if target.exists() else None
    try:
        result = tgold.finalise(draft_file, blind_entries, topics, existing=existing)
    except tgold.GoldError as exc:
        raise _fail(exc.problems) from None
    header = (
        "# The labelled set (PLAN §9.6, D-61). Reviewed by Guilherme; written by\n"
        "# `flatatlas gold finalise`. Held-out works are never used for training, calibration,\n"
        "# threshold tuning or seed sets.\n"
    )
    con = connect(settings.paths)
    try:
        with run_log(con, "gold-finalise") as run:
            write_text_atomic(target, tgold.render_gold_yaml(result, header=header))
            run.counts.update(
                {
                    "works": len(result.works),
                    "train": sum(w.split == "train" for w in result.works),
                    "heldout": sum(w.split == "heldout" for w in result.works),
                    "blind": sum(w.blind for w in result.works),
                }
            )
            counts = dict(run.counts)
    finally:
        con.close()
    typer.echo(f"wrote {target}: {counts}")


def report(
    draft_rev: Annotated[
        str, typer.Option("--draft-rev", help="Git revision holding Claude's unreviewed draft.")
    ],
    out: Annotated[Path | None, typer.Option(help="Report file.")] = None,
    profile: ProfileOption = None,
) -> None:
    """Counts per topic and split, review changes and blind agreement (gold-v1-report.md)."""
    load_settings(profile=profile)
    topics = tcheck.load_topics()
    gold_file = tcheck.load_gold()
    text = tcheck.git_head_text(DRAFT_FILE, rev=draft_rev)
    if text is None:
        raise _fail([f"{DRAFT_FILE.name} not found at {draft_rev}"])
    draft_file = tcheck.parse_gold(text, f"{draft_rev}:gold-draft.yaml")
    target = out or REPORT_FILE
    write_text_atomic(target, tgold.render_report(gold_file, draft_file, topics))
    typer.echo(f"wrote {target}")
