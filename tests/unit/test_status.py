from typer.testing import CliRunner

from flatatlas import db
from flatatlas.cli import app
from flatatlas.harvest import Page, paged
from flatatlas.settings import Settings
from flatatlas.status import render_status

runner = CliRunner()


def test_status_on_empty_data_root(settings: Settings):
    assert not settings.paths.root.exists()
    text = render_status(settings)
    assert "No warehouse yet" in text
    assert "openalex: $0.0000 of $1.00" in text
    assert not settings.paths.root.exists()  # status never creates folders


def test_status_cli_runs_on_empty_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("FLATATLAS_DATA_ROOT", str(tmp_path / "empty"))
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "No warehouse yet" in result.output


def test_status_shows_jobs_and_runs(settings: Settings):
    con = db.connect(settings.paths)
    list(paged(con, "dblp", "venue:dlt", lambda c: Page(["a", "b"], None)))
    with db.run_log(con, "harvest") as run:
        run.count("pages", 1)
    con.close()
    text = render_status(settings)
    assert "venue:dlt" in text and "done" in text
    assert "harvest" in text and '"pages": 1' in text


def test_status_reports_a_locked_warehouse(settings: Settings):
    con = db.connect(settings.paths)  # held open: a "running job"
    assert "locked by another process" in render_status(settings)
    con.close()


def test_status_budget_line_reads_the_ledger(settings: Settings, clock):
    from flatatlas.budget import BudgetLedger

    ledger = BudgetLedger(
        settings.paths.raw / "openalex" / "_budget.json", 1.0, now=clock.now, source="openalex"
    )
    ledger.charge(0.0005)
    assert "openalex: $0.0005 of $1.00" in render_status(settings)
