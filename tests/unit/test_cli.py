from typer.testing import CliRunner

from flatatlas import __version__
from flatatlas.cli import COMMAND_GROUPS, app

runner = CliRunner()

EXPECTED_GROUPS = {
    "harvest",
    "parse",
    "resolve",
    "scope",
    "embed",
    "taxonomy",
    "tag",
    "evaluate",
    "aggregate",
    "release",
    "export",
    "status",
    "venues",
}


def test_help_lists_all_command_groups():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert set(COMMAND_GROUPS) == EXPECTED_GROUPS
    for group in EXPECTED_GROUPS:
        assert group in result.output


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert __version__ in result.output
