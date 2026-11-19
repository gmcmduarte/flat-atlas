"""The ``flatatlas tag ...`` commands (P1-07). ``cli.py`` registers them on the ``tag`` group."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from flatatlas.db import connect, run_log
from flatatlas.log import setup_logging
from flatatlas.settings import load_settings
from flatatlas.tagging import runner
from flatatlas.tagging.config import CONFIG_FILE, load_config

ProfileOption = Annotated[
    str | None, typer.Option(help="Profile name (default: FLATATLAS_PROFILE or pilot).")
]
ConfigOption = Annotated[Path | None, typer.Option("--config", help="Tagger settings file.")]


def _open(profile: str | None, config: Path | None, *, write: bool):
    settings = load_settings(profile=profile)
    setup_logging(settings.paths.logs)
    cfg = load_config(config or CONFIG_FILE)
    if not settings.paths.warehouse_db.exists():
        typer.echo("error: no warehouse; run the earlier stages first", err=True)
        raise typer.Exit(1)
    con = connect(settings.paths, read_only=not write)
    return settings, cfg, con


def _prepare(settings, cfg, con):
    try:
        return runner.prepare(settings, cfg, con)
    except Exception as exc:  # a missing table or file gets a message, not a traceback
        from flatatlas.taxonomy.stage import MissingInput

        if isinstance(exc, (MissingInput, runner.Missing, FileNotFoundError)):
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        raise


def tag_run(
    ctx: typer.Context,
    method: Annotated[
        str, typer.Option(help="noisy_or (method a) or fusion (method c, learned).")
    ] = "fusion",
    limit: Annotated[
        int | None, typer.Option(help="Tag only the first N works by ID (a quick test).")
    ] = None,
    explain: Annotated[
        list[str] | None,
        typer.Option("--explain", help="Print why a work got its tags (repeatable); tags nothing."),
    ] = None,
    refit: Annotated[
        bool, typer.Option("--refit", help="Fit the fusion model again even if one is saved.")
    ] = False,
    profile: ProfileOption = None,
    config: ConfigOption = None,
) -> None:
    """Tag every work: signals, shortlist, fusion, selection (cascade steps 1 and 2).

    Writes `tag_signal` and `tag_work_topic` (one set of rows per method). The fusion model is
    fitted on gold-train and silver labels when none is saved for this `tagger_version` (a few
    minutes); held-out works are never used for training. Needs `uv sync --extra ml` for fusion.
    """
    if ctx.invoked_subcommand is not None:
        return
    if method not in runner.METHODS:
        typer.echo(f"error: --method must be one of {', '.join(runner.METHODS)}", err=True)
        raise typer.Exit(2)
    settings, cfg, con = _open(profile, config, write=not explain)
    try:
        tctx = _prepare(settings, cfg, con)
        if explain:
            for work_id in explain:
                try:
                    typer.echo(runner.explain(tctx, work_id))
                except runner.Missing as exc:
                    typer.echo(f"error: {exc}", err=True)
                    raise typer.Exit(1) from None
                typer.echo("")
            return
        with run_log(con, "tag") as run:
            # Both methods use the selection tuned on gold-train, which `fit` records.
            need_fit = refit
            if not need_fit:
                try:
                    runner.load_model(tctx)
                except runner.Missing:
                    need_fit = True
            if need_fit:
                typer.echo("fitting the models on gold-train and silver labels ...")
                tuning = runner.fit(tctx)
                typer.echo(f"  model: {tuning['model_kind']}  {tuning['fusion_selection']}")
            result = runner.tag(tctx, method, limit=limit)
            run.counts.update(
                method=method,
                works=result.n_works,
                tagged=result.n_tagged,
                untagged=len(result.untagged),
                rows=result.n_rows,
            )
        typer.echo(
            f"{method}: {result.n_tagged}/{result.n_works} works tagged, {result.n_rows} rows, "
            f"{len(result.untagged)} untagged (listed in the reports folder), "
            f"{result.low_confidence} low-confidence, unsure share {result.unsure_share:.1%}, "
            f"{result.seconds:.1f} s"
        )
    finally:
        con.close()


def fit(
    profile: ProfileOption = None,
    config: ConfigOption = None,
    write_json: Annotated[
        Path | None, typer.Option("--json", help="Also write the cross-validated numbers here.")
    ] = None,
) -> None:
    """Cross-validate methods (a) and (c) on gold-train, tune the selection, fit and save."""
    settings, cfg, con = _open(profile, config, write=True)
    try:
        tctx = _prepare(settings, cfg, con)
        with run_log(con, "tag-fit") as run:
            tuning = runner.fit(tctx)
            run.counts.update(model=tuning["model_kind"], pairs=tuning["n_pairs"])
        typer.echo(f"model {tuning['model_kind']} saved in {tctx.model_dir}")
        for name, body in tuning["cv"]["methods"].items():
            r = body["random_train"]
            typer.echo(
                f"  {name:9s} F1 level 0 {r['level0']['f1']:.3f}, level 1 {r['level1']['f1']:.3f} "
                f"(random-sample gold-train, {r['n_works']} works), unsure {r['unsure_share']:.0%}"
            )
        if write_json:
            write_json.write_text(json.dumps(tuning, indent=2, sort_keys=True), encoding="utf-8")
    finally:
        con.close()


def artefacts(
    profile: ProfileOption = None,
    config: ConfigOption = None,
    rebuild: Annotated[bool, typer.Option(help="Ignore the cache and build again.")] = False,
) -> None:
    """Build the topic artefacts and report seeds, centroids and the shortlist recall."""
    from flatatlas.tagging import shortlist as shortlist_mod

    settings, cfg, con = _open(profile, config, write=False)
    try:
        try:
            tctx = runner.prepare(settings, cfg, con, use_cache=not rebuild)
        except (runner.Missing, FileNotFoundError) as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        art = tctx.art
        n_multi = sum(1 for c in art.centroids if c is not None and len(c.counts) > 1)
        typer.echo(
            f"artefacts {art.key}: {len(tctx.dag.ids)} topics, {len(art.include)} phrases, "
            f"{len(art.exclude)} exclude phrases, {n_multi} topics with more than one centroid"
        )
        dropped = sum(len(v) for v in art.seeds_dropped.values())
        typer.echo(
            f"held-out works dropped from seed_works: {dropped} in {len(art.seeds_dropped)} topics"
        )
        for name, works in (
            ("gold-train", tctx.labels.works(split="train")),
            ("random gold-train", tctx.labels.works(split="train", sampling="random")),
        ):
            r = shortlist_mod.recall(tctx.closed, tctx.corpus.index, tctx.dag, tctx.labels, works)
            typer.echo(
                f"shortlist recall on {name}: {r['all']:.1%} (level 0 {r['level0']:.1%}, "
                f"level 1 {r['level1']:.1%}, {r['n']} labels, {len(r['misses'])} missed)"
            )
            if name == "gold-train":
                causes = shortlist_mod.miss_causes(
                    tctx.sig, r["misses"], tctx.corpus.index, tctx.dag, cfg
                )
                for cause, n in causes.items():
                    typer.echo(f"    missed, {cause}: {n}")
    finally:
        con.close()


def experiment(
    name: Annotated[str, typer.Argument(help="emb-desc | local-embedding")],
    models: Annotated[
        list[str] | None,
        typer.Option("--variant", help="Run only these variants (repeatable)."),
    ] = None,
    out: Annotated[Path | None, typer.Option("--json", help="Write the numbers here.")] = None,
    profile: ProfileOption = None,
    config: ConfigOption = None,
) -> None:
    """Run one of the two P1-07 experiments (judged on gold-train by cross-validation).

    `emb-desc` compares ways to embed the topic descriptions (the ad-hoc and the small
    sentence-transformers models download their weights on first use). `local-embedding`
    compares the local SPECTER2 input for works without a Semantic Scholar vector.
    """
    from flatatlas.tagging import descriptions, experiments, local_embed

    settings, cfg, con = _open(profile, config, write=False)
    try:
        if name == "emb-desc":

            def factory(model: str):
                c = experiments.with_config(cfg, description_model=model)
                return runner.prepare(settings, c, con, use_cache=False)

            result = experiments.emb_desc(factory, tuple(models or descriptions.MODELS))
        elif name == "local-embedding":

            def factory(variant: str):
                c = experiments.with_config(cfg, local_input=variant)
                return runner.prepare(settings, c, con, use_cache=False)

            result = experiments.local_embedding(factory, tuple(models or local_embed.VARIANTS))
        else:
            typer.echo("error: the experiments are emb-desc and local-embedding", err=True)
            raise typer.Exit(2)
        text = json.dumps(result, indent=2, sort_keys=True)
        typer.echo(text)
        if out:
            out.write_text(text, encoding="utf-8")
    finally:
        con.close()


def anchors(
    profile: ProfileOption = None,
    config: ConfigOption = None,
) -> None:
    """Where do the in-corpus anchor papers land with the learned fusion (top 3)?

    Anchors that are held-out works are left out (no held-out number is computed in P1-07);
    anchors that are gold-train works are reported apart, because the model saw their labels.
    """
    settings, cfg, con = _open(profile, config, write=False)
    try:
        tctx = _prepare(settings, cfg, con)
        try:
            result = runner.anchor_check(tctx)
        except runner.Missing as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(1) from None
        for name, body in result["groups"].items():
            typer.echo(f"{name}: {body['hit']}/{body['n']} in the top 3 ({body['rate']:.0%})")
        for miss in result["misses"]:
            typer.echo(f"  miss: {miss}")
    finally:
        con.close()
