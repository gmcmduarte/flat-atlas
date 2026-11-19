"""Local SPECTER2 vectors for works without a Semantic Scholar vector (PLAN §9.3, experiment 2).

Three inputs, chosen by ``embedding.local_input``:

- ``stored``: the vector P1-03 wrote (title, plus the abstract when there is one);
- ``title``: the title alone;
- ``title_refs``: the title, then the cleaned titles of the references the composite text holds
  (PLAN §9.3: "title plus reference titles"), in the slot where the model card puts the abstract.

Vectors are cached on disk by (model, text), so a second run loads no model.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from flatatlas.embed.specter2 import DEFAULT_SEP, VectorCache, embed_texts, format_input
from flatatlas.embed.store import normalise
from flatatlas.tagging.config import TaggerConfig
from flatatlas.tagging.inputs import Corpus


class _LazyEncoder:
    """Loads SPECTER2 on the first text that is not in the cache (a cached run loads nothing)."""

    def __init__(self, device: str) -> None:
        self.device = device
        self._encoder = None

    def encode(self, texts):
        if self._encoder is None:
            from flatatlas.embed.specter2 import load_encoder

            self._encoder = load_encoder(self.device)
        return self._encoder.encode(texts)


VARIANTS = ("stored", "title", "title_refs")


def variant_text(title: str, reference_titles: tuple[str, ...], variant: str, sep: str) -> str:
    """The text one variant embeds."""
    if variant == "title":
        return format_input(title, None, sep)[0]
    if variant == "title_refs":
        return format_input(title, "; ".join(reference_titles) or None, sep)[0]
    raise ValueError(f"unknown variant {variant!r}")


def local_rows(corpus: Corpus) -> list[int]:
    return [i for i, s in enumerate(corpus.emb_source) if s == 0]


def compute_variant(
    corpus: Corpus, variant: str, cache_dir: Path, cfg: TaggerConfig, *, encoder=None
) -> dict[int, np.ndarray]:
    """``{corpus row: unit vector}`` for every work without an S2 vector."""
    rows = local_rows(corpus)
    texts = [
        variant_text(corpus.parts[i].title, corpus.parts[i].reference_titles, variant, DEFAULT_SEP)
        for i in rows
    ]
    cache = VectorCache(cache_dir / f"local-{variant}")
    if encoder is None:
        encoder = _LazyEncoder(cfg.embedding.device)
    vectors, _stats = embed_texts(texts, encoder, batch_size=cfg.embedding.batch_size, cache=cache)
    return dict(zip(rows, normalise(vectors), strict=True))


def apply_local_input(
    corpus: Corpus, variant: str, cache_dir: Path, cfg: TaggerConfig, *, encoder=None
) -> None:
    """Replace the vectors of the works that have no S2 vector (in place)."""
    if variant == "stored":
        return
    for row, vec in compute_variant(corpus, variant, cache_dir, cfg, encoder=encoder).items():
        corpus.vectors[row] = vec
