from pathlib import Path

import pytest

from flatatlas.settings import CONFIG_DIR, load_settings
from helpers import FAKE_OPENALEX_KEY


def test_real_config_files_validate():
    for profile in ("pilot", "server"):
        settings = load_settings(profile=profile, env_file=None)
        assert settings.profile.name == profile
    assert {"dblp", "openalex", "semanticscholar", "crossref"} <= set(settings.sources)
    assert settings.sources["openalex"].daily_budget_usd == 1.0
    assert settings.sources["openalex"].costs["list"] == 0.0001


def test_data_root_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    default = load_settings(env_file=None)
    assert default.paths.root == (CONFIG_DIR.parent / "data").resolve()

    monkeypatch.setenv("FLATATLAS_DATA_ROOT", str(tmp_path / "from-env"))
    assert load_settings(env_file=None).paths.root == (tmp_path / "from-env").resolve()

    explicit = load_settings(data_root=tmp_path / "explicit", env_file=None)
    assert explicit.paths.root == (tmp_path / "explicit").resolve()
    assert explicit.paths.raw == explicit.paths.root / "raw"
    assert explicit.paths.logs == explicit.paths.root / "logs"


def test_env_file_and_empty_values(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENALEX_API_KEY=abc-key-123\nS2_API_KEY=\nCONTACT_EMAIL=me@example.org\n")
    settings = load_settings(env_file=env_file)
    assert settings.secret_for("openalex") == "abc-key-123"
    assert settings.secret_for("semanticscholar") is None  # empty means unset
    assert settings.contact_email == "me@example.org"
    assert settings.secret_for("dblp") is None


def test_secrets_are_not_shown_in_repr(settings):
    assert FAKE_OPENALEX_KEY not in repr(settings)


def test_unknown_profile(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_settings(profile="nope", env_file=None)
