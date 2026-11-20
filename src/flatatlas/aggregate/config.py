"""``config/aggregate.yaml``: every number behind an edge, an aggregate or a position."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from flatatlas.settings import CONFIG_DIR

CONFIG_FILE = CONFIG_DIR / "aggregate.yaml"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RelatedConfig(_Section):
    min_support: int = Field(5, ge=1)
    npmi_min: float = 0.1
    min_confidence: float = 0.5
    bootstrap: int = Field(200, ge=1)


class BuildsOnConfig(_Section):
    min_flow: float = 5.0
    max_p: float = 0.05
    permutations: int = Field(1000, ge=1)
    stratum_years: int = Field(5, ge=1)


class SharedCommunityConfig(_Section):
    min_shared_authors: int = Field(3, ge=1)
    cosine_min: float = 0.1
    min_confidence: float = 0.5
    bootstrap: int = Field(200, ge=1)


class ForceAtlasConfig(_Section):
    iterations: int = Field(600, ge=1)
    gravity: float = 1.0
    scaling: float = 0.5
    edge_weight_influence: float = 1.0
    overlap_gap: float = 4.0


class LayoutConfig(_Section):
    seed: int = 20261120
    root_radius: float = 100.0
    min_radius_share: float = 0.08
    fill: float = 0.9
    pad: float = 0.05
    fa2: ForceAtlasConfig = Field(default_factory=ForceAtlasConfig)
    decimals: int = 3


class AggregateConfig(_Section):
    aggregate_version: str
    seed: int = 20261120
    present_min: float = 0.35
    top_k: int = Field(10, ge=1)
    related: RelatedConfig = Field(default_factory=RelatedConfig)
    builds_on: BuildsOnConfig = Field(default_factory=BuildsOnConfig)
    shared_community: SharedCommunityConfig = Field(default_factory=SharedCommunityConfig)
    layout: LayoutConfig = Field(default_factory=LayoutConfig)


def load_config(path: Path = CONFIG_FILE) -> AggregateConfig:
    return AggregateConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
