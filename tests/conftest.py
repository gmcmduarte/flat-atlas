from __future__ import annotations

from pathlib import Path

import pytest

from flatatlas.settings import Settings, load_settings
from helpers import FAKE_EMAIL, FAKE_OPENALEX_KEY, FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never see a developer's real keys or settings."""
    for name in (
        "OPENALEX_API_KEY",
        "S2_API_KEY",
        "CONTACT_EMAIL",
        "FLATATLAS_PROFILE",
        "FLATATLAS_DATA_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """The real ``config/`` files, a throwaway data root, fake credentials, no ``.env``."""
    monkeypatch.setenv("OPENALEX_API_KEY", FAKE_OPENALEX_KEY)
    monkeypatch.setenv("CONTACT_EMAIL", FAKE_EMAIL)
    return load_settings(data_root=tmp_path / "data", env_file=None)
