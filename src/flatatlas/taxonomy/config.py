"""``config/taxonomy.yaml``: every knob of the mining, clustering and proposal steps."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from flatatlas.settings import CONFIG_DIR

CONFIG_FILE = CONFIG_DIR / "taxonomy.yaml"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeedsConfig(_Section):
    ccs_file: str = "raw/seeds/acm-ccs.xml"
    ccs_subtrees: list[str] = Field(default_factory=list)
    ccs_single: list[str] = Field(default_factory=list)
    openalex_min_works: int = 2


class BackgroundConfig(_Section):
    n_titles: int = 5000
    per_page: int = 200
    filter: str = ""
    exclude_title_words: list[str] = Field(default_factory=list)


class MineConfig(_Section):
    min_ngram: int = 1
    max_ngram: int = 4
    min_docs: int = 3
    reference_weight: float = 0.3
    title_weight: float = 1.0
    abstract_weight: float = 0.7
    tldr_weight: float = 0.7
    top_candidates: int = 600
    merge_embedding_cosine: float = 0.9


class ClusterConfig(_Section):
    granularities: list[int] = Field(default_factory=lambda: [12, 30, 70])
    min_samples: int = 3
    umap_neighbors: int = 15
    umap_components: int = 10
    umap_min_dist: float = 0.0
    label_terms: int = 6


class ProposeConfig(_Section):
    max_topics: int = 400
    min_topic_size: int = 5
    min_specificity: float = 0.85
    min_unigram_specificity: float = 0.99
    exclude_phrases: list[str] = Field(default_factory=list)
    synonym_jaccard: float = 0.8
    cluster_match_jaccard: float = 0.5
    subsumption_parent_given_child: float = 0.7
    subsumption_child_given_parent: float = 0.5
    min_link_score: float = 2.0
    soft_attach_containment: float = 0.4
    citation_min_share: float = 0.2
    max_parents: int = 3
    examples_per_topic: int = 5


class TaxonomyConfig(_Section):
    seed: int = 20261116
    seeds: SeedsConfig = Field(default_factory=SeedsConfig)
    background: BackgroundConfig = Field(default_factory=BackgroundConfig)
    mine: MineConfig = Field(default_factory=MineConfig)
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    propose: ProposeConfig = Field(default_factory=ProposeConfig)


def load_config(path: Path = CONFIG_FILE) -> TaxonomyConfig:
    return TaxonomyConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def config_hash(config: TaxonomyConfig) -> str:
    """A short digest of the settings (recorded in outputs, so runs can be compared)."""
    text = config.model_dump_json()
    return hashlib.sha256(text.encode()).hexdigest()[:10]
