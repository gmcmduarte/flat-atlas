"""``config/resolve.yaml``: every threshold of the resolve stage (PLAN §8)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from flatatlas.settings import CONFIG_DIR

RESOLVE_FILE = CONFIG_DIR / "resolve.yaml"


class ResolveConfigError(ValueError):
    """The file is missing a value or has a bad one."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceMatchConfig(_Model):
    title_min: float = Field(0.93, ge=0, le=1)
    year_tolerance: int = Field(1, ge=0)
    first_author_surname: bool = True
    no_author_confidence_cap: float = Field(0.9, ge=0, le=1)


class CandidateConfig(_Model):
    shared_authors_min: int = Field(1, ge=1)
    max_year_gap: int = Field(6, ge=0)
    title_min: float = Field(0.6, ge=0, le=1)


class WeightsConfig(_Model):
    title: float = Field(ge=0)
    authors: float = Field(ge=0)
    embedding: float = Field(ge=0)
    extra: float = Field(ge=0)

    @model_validator(mode="after")
    def _sum_to_one(self) -> WeightsConfig:
        total = self.title + self.authors + self.embedding + self.extra
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"weights must sum to 1, they sum to {total}")
        return self


class ExtraValues(_Model):
    same_external_record: float = Field(1.0, ge=0, le=1)
    external_record_names_other: float = Field(0.5, ge=0, le=1)
    cites: float = Field(1.0, ge=0, le=1)
    special_issue: float = Field(1.0, ge=0, le=1)


class VersionsConfig(_Model):
    merge_min: float = Field(ge=0, le=1)
    report_min: float = Field(ge=0, le=1)
    candidate: CandidateConfig = CandidateConfig()
    weights: WeightsConfig
    embedding_floor: float = Field(0.7, ge=0, lt=1)
    extra_values: ExtraValues = ExtraValues()
    strip_title_markers: list[str] = []

    @model_validator(mode="after")
    def _ordered(self) -> VersionsConfig:
        if self.report_min > self.merge_min:
            raise ValueError("report_min must not exceed merge_min")
        return self


class AuthorsConfig(_Model):
    name_match_min: float = Field(0.85, ge=0, le=1)
    min_papers: int = Field(2, ge=1)
    min_share: float = Field(0.8, ge=0, le=1)
    orcid_min_papers: int = Field(1, ge=1)


class ScopeConfig(_Model):
    tier_a_status: str = "core"
    tier_a_score: float = Field(1.0, ge=0, le=1)
    tier_a_reason: str = "tier A venue (venues.yaml)"


class QualityConfig(_Model):
    min_share_openalex: float = Field(0.9, ge=0, le=1)
    min_share_s2: float = Field(0.9, ge=0, le=1)
    min_share_crossref_of_doi: float = Field(0.95, ge=0, le=1)
    max_uncertain_pairs: int = Field(50, ge=0)
    histogram_edges: list[float] = [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0]


class ResolveConfig(_Model):
    source_match: SourceMatchConfig = SourceMatchConfig()
    versions: VersionsConfig
    authors: AuthorsConfig = AuthorsConfig()
    scope: ScopeConfig = ScopeConfig()
    quality: QualityConfig = QualityConfig()


def parse_resolve_config(raw: object) -> ResolveConfig:
    try:
        return ResolveConfig.model_validate(raw or {})
    except ValidationError as exc:
        problems = [
            f"resolve.yaml: {'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()
        ]
        raise ResolveConfigError("\n".join(problems)) from None


def load_resolve_config(path: Path = RESOLVE_FILE) -> ResolveConfig:
    with path.open(encoding="utf-8") as handle:
        return parse_resolve_config(yaml.safe_load(handle))
