"""Settings: secrets from ``.env``, a profile, and the per-source access table.

Profiles live in ``config/profiles/``; sources in ``config/sources.yaml``.

``load_settings()`` is the single entry point. Tests call it with ``env_file=None`` so they never
read a developer's ``.env``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from flatatlas.log import register_secret

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
ENV_FILE = PROJECT_ROOT / ".env"


class EnvSettings(BaseSettings):
    """Values from ``.env`` or the process environment. Empty values count as unset."""

    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    openalex_api_key: SecretStr | None = None
    s2_api_key: SecretStr | None = None
    contact_email: str | None = None
    flatatlas_profile: str = "pilot"
    flatatlas_data_root: Path | None = None


class Profile(BaseModel):
    """One file in ``config/profiles/`` (PLAN §5.4)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    data_root: Path = Path("data")
    active_venues: list[str] | Literal["all"]
    concurrency: int = Field(1, ge=1)
    embedding_device: Literal["mps", "cpu", "cuda"] = "cpu"
    batch_sizes: dict[str, int] = {}
    bulk_loaders_enabled: bool = False
    export_targets: list[str] = []


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style: Literal["none", "query", "header"] = "none"
    name: str | None = None  # query parameter or header name
    secret: str | None = None  # EnvSettings field that holds the key
    required: bool = False

    def model_post_init(self, __context: object) -> None:
        if self.style != "none" and not (self.name and self.secret):
            raise ValueError("auth styles 'query' and 'header' need both 'name' and 'secret'")


class SourceConfig(BaseModel):
    """One entry of ``config/sources.yaml``."""

    model_config = ConfigDict(extra="forbid")

    base_url: str
    requests_per_second: float = Field(gt=0)
    burst: int = Field(1, ge=1)
    batch_size: int = Field(1, ge=1)
    daily_budget_usd: float | None = None
    costs: dict[str, float] = {}
    auth: AuthConfig = AuthConfig()
    mailto_param: str | None = None
    timeout_seconds: float = 30.0
    max_attempts: int = Field(6, ge=1)
    max_backoff_seconds: float = 60.0
    max_retry_wait_seconds: float = 300.0  # refuse a Retry-After longer than this


@dataclass(frozen=True)
class Paths:
    """Folders under the data root (PLAN §16). Nothing is created until ``ensure()``."""

    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def warehouse(self) -> Path:
        return self.root / "warehouse"

    @property
    def releases(self) -> Path:
        return self.root / "releases"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def cache(self) -> Path:
        """Recomputable intermediate results (for example finished embedding batches)."""
        return self.root / "cache"

    @property
    def review(self) -> Path:
        """Local review sheets (they may hold abstracts, so they are never committed)."""
        return self.root / "review"

    @property
    def warehouse_db(self) -> Path:
        return self.warehouse / "flatatlas.duckdb"

    def ensure(self) -> None:
        for folder in (self.raw, self.warehouse, self.releases, self.reports, self.logs):
            folder.mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    env: EnvSettings
    profile: Profile
    sources: dict[str, SourceConfig]
    paths: Paths

    @property
    def contact_email(self) -> str | None:
        return self.env.contact_email

    def secret_for(self, source: str) -> str | None:
        """The API key configured for ``source``, or None."""
        auth = self.sources[source].auth
        if auth.secret is None:
            return None
        value: SecretStr | None = getattr(self.env, auth.secret, None)
        return value.get_secret_value() if value else None


def _read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return data


def load_settings(
    *,
    profile: str | None = None,
    data_root: Path | None = None,
    env_file: Path | None = ENV_FILE,
    config_dir: Path = CONFIG_DIR,
) -> Settings:
    """Load settings. Data root precedence: argument, ``FLATATLAS_DATA_ROOT``, profile file."""
    env = EnvSettings(_env_file=env_file)
    profile_name = profile or env.flatatlas_profile
    profile_path = config_dir / "profiles" / f"{profile_name}.yaml"
    if not profile_path.exists():
        raise FileNotFoundError(f"No such profile: {profile_path}")
    prof = Profile.model_validate(_read_yaml(profile_path))
    sources = {
        name: SourceConfig.model_validate(body)
        for name, body in _read_yaml(config_dir / "sources.yaml").items()
    }

    root = data_root or env.flatatlas_data_root or prof.data_root
    if not root.is_absolute():
        root = config_dir.parent / root

    for secret in (env.openalex_api_key, env.s2_api_key):
        if secret is not None:
            register_secret(secret.get_secret_value())
    return Settings(env=env, profile=prof, sources=sources, paths=Paths(root.resolve()))
