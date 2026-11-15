"""``flatatlas status``: what has been harvested and which runs happened."""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb

from flatatlas.budget import BudgetLedger
from flatatlas.db import connect
from flatatlas.settings import Settings

RECENT_RUNS = 10


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    return ["  " + fmt.format(*headers).rstrip()] + ["  " + fmt.format(*r).rstrip() for r in rows]


def _budget_lines(settings: Settings) -> list[str]:
    lines: list[str] = []
    for name, cfg in settings.sources.items():
        if cfg.daily_budget_usd is None:
            continue
        ledger = BudgetLedger(
            settings.paths.raw / name / "_budget.json",
            cfg.daily_budget_usd,
            now=lambda: datetime.now(UTC),
            source=name,
        )
        lines.append(
            f"  {name}: ${ledger.spent_today_usd():.4f} of ${cfg.daily_budget_usd:.2f} (UTC today)"
        )
    return lines


def render_status(settings: Settings) -> str:
    out = [
        f"Profile: {settings.profile.name}",
        f"Data root: {settings.paths.root}",
        "",
        "Budgets",
        *_budget_lines(settings),
        "",
    ]
    db_path = settings.paths.warehouse_db
    if not db_path.exists():
        out.append("No warehouse yet: nothing has been harvested.")
        return "\n".join(out)

    try:
        con = connect(db_path, read_only=True)
    except (duckdb.IOException, duckdb.ConnectionException):
        out.append(f"The warehouse {db_path} is locked by another process (a running job?).")
        return "\n".join(out)

    try:
        states = con.execute(
            'SELECT source, job_key, status, n_items, updated_at, "cursor" '
            "FROM ops_harvest_state ORDER BY source, job_key"
        ).fetchall()
        runs = con.execute(
            "SELECT stage, status, started, finished, counts FROM ops_run_log "
            f"ORDER BY started DESC LIMIT {RECENT_RUNS}"
        ).fetchall()
    except duckdb.CatalogException:
        out.append("The warehouse exists but has no operational tables yet.")
        return "\n".join(out)
    finally:
        con.close()

    out.append("Harvest jobs")
    if states:
        rows = [
            [s, j, st, str(n), f"{u:%Y-%m-%d %H:%M}", (c or "-")[:30]]
            for s, j, st, n, u, c in states
        ]
        out += _table(["source", "job", "status", "items", "updated (UTC)", "cursor"], rows)
    else:
        out.append("  none")

    out += ["", f"Last {RECENT_RUNS} runs"]
    if runs:
        rows = [
            [stage, status, f"{started:%Y-%m-%d %H:%M}", f"{finished:%H:%M}" if finished else "-",
             counts or "-"]
            for stage, status, started, finished, counts in runs
        ]  # fmt: skip
        out += _table(["stage", "status", "started (UTC)", "ended", "counts"], rows)
    else:
        out.append("  none")
    return "\n".join(out)
