"""``flatatlas evaluate freeze | check | report`` and ``flatatlas evaluate --heldout`` (P1-08)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from flatatlas.db import connect, run_log, write_text_atomic
from flatatlas.evaluate import checks, report_data
from flatatlas.evaluate import freeze as freeze_mod
from flatatlas.evaluate import heldout as heldout_mod
from flatatlas.evaluate import report as report_mod
from flatatlas.evaluate.variants import KEYS, key_of
from flatatlas.log import setup_logging
from flatatlas.quality import record
from flatatlas.settings import PROJECT_ROOT, load_settings
from flatatlas.tagging import runner
from flatatlas.tagging.commands import ConfigOption, ProfileOption, _open, _prepare
from flatatlas.tagging.config import CONFIG_FILE, TaggerConfig, load_config

RunOption = Annotated[
    str | None, typer.Option("--run", help="Run ID (default: from the settings).")
]


def adopted_key(cfg: TaggerConfig) -> str:
    return key_of(cfg.method, cfg.decision_model.enabled, cfg.propagation.enabled)


def _frozen(reports: Path, cfg: TaggerConfig, run: str | None) -> dict:
    path = freeze_mod.frozen_path(reports, run or freeze_mod.default_run_id(cfg))
    if not path.exists():
        typer.echo(
            f"error: no frozen record {path}; run `flatatlas evaluate freeze` first", err=True
        )
        raise typer.Exit(1)
    return json.loads(path.read_text("utf-8"))


def _write_report(ctx: runner.Context, frozen: dict, held: dict | None) -> Path:
    cfg = ctx.cfg
    adopted = adopted_key(cfg)
    probs = report_data.load_variant_probs(frozen, adopted, ctx.corpus, ctx.dag)
    other_key = "fusion" if adopted.startswith("noisy_or") else "noisy_or"
    other = report_data.load_variant_probs(frozen, other_key, ctx.corpus, ctx.dag)
    sel = frozen["variants"][adopted]["selection"]
    sels = checks.select_all(probs, len(ctx.corpus), ctx.dag, sel, cfg.selection.fallback_min)
    links = report_data.work_links(ctx.con, ctx.corpus)
    topics = report_data.topic_rows(frozen, adopted, sels, ctx.dag, cfg)
    spot = report_data.spot_lists(
        ctx.corpus, ctx.dag, sels, probs, other, links, cfg, report_mod.LABELS[other_key]
    )
    notes = [
        "The highlighted variant is the one config/tagger.yaml selects now: "
        f"{report_mod.LABELS[adopted]}."
    ]
    page = report_mod.render(frozen, held, topics, spot, adopted=adopted, notes=notes)
    out = PROJECT_ROOT / "reports" / f"eval-{frozen['run_id']}.html"
    write_text_atomic(out, page)
    return out


def freeze_cmd(
    run: RunOption = None,
    after_opening: Annotated[
        bool, typer.Option("--after-opening", help="Allow a freeze after the held-out opening.")
    ] = False,
    profile: ProfileOption = None,
    config: ConfigOption = None,
) -> None:
    """Fit the eight variants on gold-train, run the label-free checks, write the frozen record.

    Reads no held-out label. Writes data/reports/frozen-<run>.json and a draft HTML report.
    """
    settings, cfg, con = _open(profile, config, write=False)
    reports = settings.paths.reports
    if heldout_mod.lock_path(reports).exists() and not after_opening:
        typer.echo(
            "error: the held-out set has been opened; freezing again would be tuning after the "
            "fact. Use --after-opening to do it anyway (the numbers are then optimistic).",
            err=True,
        )
        raise typer.Exit(1)
    try:
        ctx = _prepare(settings, cfg, con)
        cfg2 = cfg.model_copy(update={"seed": cfg.evaluation.stability_seed})
        ctx2 = _prepare(settings, cfg2, con)
        run_id = run or freeze_mod.default_run_id(cfg)
        frozen = freeze_mod.freeze(ctx, ctx2, run_id=run_id, reports=reports, log=typer.echo)
        path = _write_report(ctx, frozen, None)
    finally:
        con.close()
    typer.echo(f"frozen {freeze_mod.frozen_path(reports, run_id)}")
    typer.echo(f"draft report {path}")


def check_cmd(
    run: RunOption = None,
    record_results: Annotated[bool, typer.Option("--record/--no-record")] = True,
    frozen_file: Annotated[
        Path | None, typer.Option("--frozen", help="A frozen record file.")
    ] = None,
    profile: ProfileOption = None,
    config: ConfigOption = None,
) -> None:
    """Hard checks of the adopted variant; exit code 1 if one fails (every variant is recorded)."""
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    cfg = load_config(config or CONFIG_FILE)
    if frozen_file is not None:
        frozen = json.loads(frozen_file.read_text("utf-8"))
    else:
        frozen = _frozen(settings.paths.reports, cfg, run)
    results = freeze_mod.results_for_ops(frozen, cfg, adopted_key(cfg))
    if record_results and settings.paths.warehouse_db.exists():
        con = connect(settings.paths)
        try:
            with run_log(con, "evaluate-tagger") as r:
                record(con, f"{frozen['run_id']}", results, log=None)
                r.counts.update(checks=str(len(results)))
        finally:
            con.close()
    failed = [r for r in results if not r.passed]
    for r in results:
        if r.check.endswith(f"[{adopted_key(cfg)}]"):
            status = "ok  " if r.passed else "FAIL"
            typer.echo(f"{status} {r.check}: {r.value:.3f} (threshold {r.threshold})")
    if failed:
        typer.echo(f"{len(failed)} hard check(s) of the adopted variant failed")
        raise typer.Exit(1)
    typer.echo("all hard checks of the adopted variant pass")


def heldout_cmd(
    run: RunOption = None,
    again: Annotated[
        bool, typer.Option("--again", help="Open again; numbers are optimistic.")
    ] = False,
    profile: ProfileOption = None,
    config: ConfigOption = None,
) -> None:
    """Open the held-out set once for all eight variants (PLAN §9.6)."""
    settings, cfg, con = _open(profile, config, write=False)
    reports = settings.paths.reports
    try:
        frozen = _frozen(reports, cfg, run)
        ctx = _prepare(settings, cfg, con)
        try:
            res = heldout_mod.open_heldout(
                frozen, cfg, ctx.corpus, ctx.dag, ctx.labels, reports,
                again=again, gold_path=ctx.gold_path, topics_path=ctx.topics_path,
            )  # fmt: skip
        except heldout_mod.HeldoutRefused as exc:
            typer.echo(f"refused: {exc}", err=True)
            raise typer.Exit(1) from None
        path = _write_report(ctx, frozen, res)
    finally:
        con.close()
    typer.echo(
        f"held-out set opened ({res['n_works']} works){' [optimistic: again]' if again else ''}"
    )
    for key in KEYS:
        e = res["estimates"][key]
        typer.echo(
            f"  {key:16s} L0 F1 {e['f0'][0]:.3f} ({e['f0'][1]:.3f}-{e['f0'][2]:.3f})  "
            f"L1 F1 {e['f1'][0]:.3f} ({e['f1'][1]:.3f}-{e['f1'][2]:.3f})  mean {e['mean_f'][0]:.3f}"
        )
    d = res["decision"]
    typer.echo(f"rule says: adopt {d['adopted']}")
    for key, r in d["rungs"].items():
        typer.echo(
            f"  {key:16s} vs {r['against']:12s} {r['diff']:+.3f} ({r['lo']:+.3f} to {r['hi']:+.3f})"
            f"  {'ADOPT' if r['adopt'] else 'no'}"
        )
    typer.echo(f"report {path}")
    # the hard checks of the variant the settings select, so the exit code reflects them
    results = freeze_mod.results_for_ops(frozen, cfg, adopted_key(cfg))
    if any(not r.passed for r in results):
        typer.echo("hard check(s) of the currently selected variant failed")
        raise typer.Exit(1)


def report_cmd(
    run: RunOption = None, profile: ProfileOption = None, config: ConfigOption = None
) -> None:
    """Rewrite reports/eval-<run>.html from the frozen record (and the held-out numbers if any)."""
    settings, cfg, con = _open(profile, config, write=False)
    reports = settings.paths.reports
    try:
        frozen = _frozen(reports, cfg, run)
        held_path = reports / f"heldout-{frozen['run_id']}.json"
        held = json.loads(held_path.read_text("utf-8")) if held_path.exists() else None
        ctx = _prepare(settings, cfg, con)
        path = _write_report(ctx, frozen, held)
    finally:
        con.close()
    typer.echo(f"report {path}")
