"""``config/tagger.yaml``: every weight, band, threshold, seed and model setting of the tagger."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from flatatlas.settings import CONFIG_DIR

CONFIG_FILE = CONFIG_DIR / "tagger.yaml"

SIGNALS = (
    "lex_title",
    "lex_abstract",
    "lex_refs",
    "emb_seed",
    "emb_desc",
    "src_openalex",
    "venue_prior",
)
# Signal families for the shortlist and the agreement bonus (PLAN §9.3, §9.4).
FAMILIES: dict[str, tuple[str, ...]] = {
    "lexical": ("lex_title", "lex_abstract", "lex_refs"),
    "embedding": ("emb_seed", "emb_desc"),
    "source": ("src_openalex",),
}


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DecisionSelectConfig(_Section):
    # Besides the unsure band (`selection.unsure_band`), a work is also sent when two signal
    # families each reach `noisy_or.agreement.family_min` for different level-0 topics.
    disagreement: bool = True


class DecisionModelConfig(_Section):
    """Cascade step 3 (PLAN §9.5): a local open model read for option probabilities."""

    enabled: bool = False  # off: no dm_* signal reaches the fusion model
    model_file: str = "llm/qwen3-8b-q4km/Qwen3-8B-Q4_K_M.gguf"  # relative to data/models/
    model_name: str = "Qwen3-8B-Q4_K_M"
    quantisation: str = "Q4_K_M"
    n_ctx: int = 4096
    n_threads: int | None = None  # None: the runtime decides
    option_orders: int = 3  # fixed orders of the level-0 options, 1 to 3
    top_l0: int = 2  # yes/no questions for the children of this many most probable topics
    max_child_questions: int = 8  # at most this many yes/no questions per work
    child_max_level: int = 1  # deeper topics have no labels, so no calibration (D-98)
    flush_every: int = 10  # works between writes of the answer cache
    select: DecisionSelectConfig = Field(default_factory=DecisionSelectConfig)


class PhrasesConfig(_Section):
    weight_include: float = 1.0
    weight_alias: float = 0.95
    weight_name: float = 0.9
    weight_variant: float = 0.85
    weight_neighbour: float = 0.4
    neighbour_min_cosine: float = 0.95
    neighbour_min_tokens: int = 2
    single_token_factor: float = 0.7
    max_title_seeds: int = 30


class SignalsConfig(_Section):
    lex_abstract_scale: float = 1.5
    percentile_floor: float = 0.9
    openalex_min_score: float = 0.1
    venue_smoothing: float = 1.0


class EmbeddingConfig(_Section):
    local_input: str = "title_refs"
    description_model: str = "specter2"
    batch_size: int = 16
    device: str = "cpu"
    centroid_spread_split: float = 0.05
    max_centroids: int = 3
    min_seeds_per_centroid: int = 4
    kmeans_iterations: int = 50


class ShortlistConfig(_Section):
    size: int = 10
    min_percentile: float = 0.8  # an embedding candidate needs at least this percentile
    per_family: dict[str, int] = Field(
        default_factory=lambda: {"lexical": 4, "emb_seed": 4, "emb_desc": 2, "source": 1}
    )


class AgreementConfig(_Section):
    family_min: float = 0.35
    bonus: float = 0.2


class NoisyOrConfig(_Section):
    weights: dict[str, float]
    agreement: AgreementConfig = Field(default_factory=AgreementConfig)


class SilverConfig(_Section):
    min_negative_gap: float = 0.15
    positive_min_title: float = 0.85
    max_per_class: int = 6000


class LightGbmConfig(_Section):
    n_estimators: int = 200
    learning_rate: float = 0.05
    num_leaves: int = 7
    min_child_samples: int = 20
    subsample: float = 0.8
    subsample_freq: int = 1
    colsample_bytree: float = 0.8
    reg_lambda: float = 1.0


class LogisticConfig(_Section):
    C: float = 1.0
    max_iter: int = 500


class FusionConfig(_Section):
    folds: int = 5
    weight_gold: float = 3.0
    weight_silver: float = 1.0
    calibrate_on: str = "random"
    choose_by: str = "f1_micro_l1"
    complex_margin: float = 0.01
    bag: int = 1  # models averaged over seeds (1: a single model; P1-08 sets 5, D-100)
    bag_seed_step: int = 101  # member k is fitted with seed + k * step
    lightgbm: LightGbmConfig = Field(default_factory=LightGbmConfig)
    logistic: LogisticConfig = Field(default_factory=LogisticConfig)


class SelectionConfig(_Section):
    threshold: float = 0.35
    max_topics: int = 6
    tune_threshold: list[float] = Field(default_factory=lambda: [0.35])
    tune_max_topics: list[int] = Field(default_factory=lambda: [6])
    fallback_min: float = 0.15
    unsure_band: tuple[float, float] = (0.3, 0.5)


class PropagationConfig(_Section):
    """Pass 2 (P1-08, PLAN §9.3, D-25): topic vectors of the graph neighbours as two signals."""

    enabled: bool = False  # the shipped model reads prop_cite and prop_author
    ref_weight: float = 1.0  # a reference counts this much in prop_cite
    citer_weight: float = 0.5  # an in-corpus citer counts this much (references count more)
    influential_boost: float = 1.5  # multiplies an edge Semantic Scholar marks influential
    author_window: int = 5  # years either side of the work for the authors' other works
    noisy_or_weights: dict[str, float] = Field(
        default_factory=lambda: {"prop_cite": 0.4, "prop_author": 0.15}
    )


class TopDownConfig(_Section):
    """Method (b), the top-down baseline (PLAN §9.4): a small classifier per level on embeddings."""

    C: float = 0.1  # inverse regularisation; best of 0.001 to 10 by gold-train CV (P1-08)
    min_positives: int = 2  # a topic with fewer gold positives gets no classifier
    min_negatives: int = 2


class EvaluationConfig(_Section):
    """Thresholds and settings of ``flatatlas evaluate`` (PLAN §9.6); hard ones fail the run."""

    anchors_min: float = 0.90  # hard: share of in-corpus anchors in the top 3 topics
    coverage_min: float = 0.85  # hard: share of works with at least one non-derived tag
    stability_min: float = 0.95  # hard: share of primary tags unchanged under another seed
    stability_seed: int = 20261121
    venue_top: int = 3  # a venue's expected topics must be among its top level-0 topics
    bootstrap_n: int = 2000
    bootstrap_seed: int = 20261122
    interval: float = 0.90  # central bootstrap interval
    calibration_bins: int = 10
    agreement_flag: float = 0.2  # topics with method agreement below this are flagged
    coherence_margin: float = 0.0  # a topic is flagged when its cosine is below random + margin
    leak_sample: int = 200  # works whose lex_title is hidden in the hold-out leak test
    spot_n: int = 10  # works per list per topic in the spot-check report


class TaggerConfig(_Section):
    tagger_version: str
    seed: int = 20261120
    method: str = "fusion"  # the method that ships: noisy_or | fusion (P1-08 decides, D-100)
    propagation: PropagationConfig = Field(default_factory=PropagationConfig)
    topdown: TopDownConfig = Field(default_factory=TopDownConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    decision_model: DecisionModelConfig = Field(default_factory=DecisionModelConfig)
    phrases: PhrasesConfig = Field(default_factory=PhrasesConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    shortlist: ShortlistConfig = Field(default_factory=ShortlistConfig)
    noisy_or: NoisyOrConfig
    silver: SilverConfig = Field(default_factory=SilverConfig)
    fusion: FusionConfig = Field(default_factory=FusionConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)


def load_config(path: Path = CONFIG_FILE) -> TaggerConfig:
    return TaggerConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def config_hash(config: TaggerConfig, *, exclude: set[str] | None = None) -> str:
    """A short digest of the settings that decide artefacts and models (recorded with them)."""
    text = config.model_dump_json(exclude=exclude or set())
    return hashlib.sha256(text.encode()).hexdigest()[:10]


def artefact_hash(config: TaggerConfig) -> str:
    """Digest of the settings the topic artefacts depend on (not the fusion or selection)."""
    parts = config.model_dump(include={"phrases", "embedding", "signals", "seed"})
    return hashlib.sha256(repr(sorted(parts.items())).encode()).hexdigest()[:10]
