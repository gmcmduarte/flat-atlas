"""Embedding the topic descriptions (and, for a general model, the works) for ``emb_desc``.

Three choices, settled by experiment 1 of P1-07 (``docs/notes/tagger-experiments.md``):

- ``specter2``: the proximity adapter of the model that embeds the works, applied to the topic text.
- ``specter2_adhoc``: the ad-hoc *query* adapter on the topic text, compared with the proximity
  vectors of the works (the use the SPECTER2 card describes for short queries).
- ``minilm``: one small general sentence-transformers model, for the topic text and the composite
  text of each work.

The models are loaded only when asked for (they need the ``ml`` extra and, the first time, a
download of the weights). Vectors are cached on disk by (model, text).
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from flatatlas.embed.specter2 import BASE_MODEL, MAX_LENGTH, MissingMlExtra, Specter2Encoder
from flatatlas.embed.store import normalise
from flatatlas.taxonomy.schema import TopicEntry
from flatatlas.text.composite import CompositeParts, compose

ADHOC_ADAPTER = "allenai/specter2_adhoc_query"
MINILM = "sentence-transformers/all-MiniLM-L6-v2"
MODELS = ("specter2", "specter2_adhoc", "minilm")


def topic_text(topic: TopicEntry) -> str:
    """What is embedded for a topic: its name and description."""
    description = " ".join(topic.description.split())
    return f"{topic.name}. {description}" if description else topic.name


@dataclass
class DescSpace:
    """Topic vectors and, when the model is not the one that embeds the works, work vectors."""

    model: str
    topic_vectors: np.ndarray  # (topics, d), unit length
    work_vectors: np.ndarray | None = None  # (works, d) unit length; None: use the corpus vectors


class _Cache:
    """Vectors on disk by (model, text hash): one small ``.npz`` per call."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    @staticmethod
    def key(model: str, text: str) -> str:
        return hashlib.sha256(f"{model}\x00{text}".encode()).hexdigest()

    def load(self) -> dict[str, np.ndarray]:
        found: dict[str, np.ndarray] = {}
        for path in sorted(self.folder.glob("*.npz")):
            try:
                with np.load(path) as shard:
                    for h, v in zip(shard["hashes"].tolist(), shard["vectors"], strict=True):
                        found[str(h)] = v
            except (OSError, ValueError, KeyError):
                continue
        return found

    def save(self, hashes: Sequence[str], vectors: np.ndarray) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha1("".join(hashes).encode()).hexdigest()[:16]  # noqa: S324
        tmp = self.folder / f".{name}.{uuid.uuid4().hex}.tmp.npz"
        try:
            np.savez(tmp, hashes=np.array(list(hashes)), vectors=vectors.astype(np.float32))
            os.replace(tmp, self.folder / f"{name}.npz")
        finally:
            tmp.unlink(missing_ok=True)


def _encode_cached(model: str, texts: list[str], encode, cache_dir: Path, batch: int) -> np.ndarray:
    cache = _Cache(cache_dir / model.replace("/", "_"))
    have = cache.load()
    keys = [cache.key(model, t) for t in texts]
    todo = sorted({k: t for k, t in zip(keys, texts, strict=True) if k not in have}.items())
    for start in range(0, len(todo), batch):
        chunk = todo[start : start + batch]
        vectors = np.asarray(encode([t for _k, t in chunk]), dtype=np.float32)
        cache.save([k for k, _t in chunk], vectors)
        for (k, _t), v in zip(chunk, vectors, strict=True):
            have[k] = v
    return np.vstack([have[k] for k in keys])


class _AdhocEncoder(Specter2Encoder):
    """SPECTER2 with the ad-hoc query adapter (for short texts that describe a topic)."""

    def __init__(self, device: str = "cpu") -> None:
        try:
            from adapters import AutoAdapterModel
            from transformers import AutoTokenizer
        except ImportError as exc:  # pragma: no cover
            raise MissingMlExtra("run `uv sync --extra ml`") from exc
        import torch

        from flatatlas.embed.specter2 import resolve_device

        self._torch = torch
        self.device = resolve_device(device)
        self.tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
        model = AutoAdapterModel.from_pretrained(BASE_MODEL)
        model.load_adapter(ADHOC_ADAPTER, source="hf", load_as="adhoc_query", set_active=True)
        self.model = model.to(self.device).eval()
        if not self.model.active_adapters:
            raise RuntimeError("the ad-hoc query adapter did not become active")
        self.sep = self.tokenizer.sep_token or "[SEP]"


def describe(
    model: str,
    topics: Sequence[TopicEntry],
    parts: Sequence[CompositeParts],
    cache_dir: Path,
    *,
    device: str = "cpu",
    batch_size: int = 16,
) -> DescSpace:
    """Embed the topic texts (and the works, for ``minilm``) with ``model``."""
    texts = [topic_text(t) for t in topics]
    if model == "specter2":
        encoder = Specter2Encoder(device)
        vec = _encode_cached("specter2-proximity", texts, encoder.encode, cache_dir, batch_size)
        return DescSpace(model, normalise(vec))
    if model == "specter2_adhoc":
        encoder = _AdhocEncoder(device)
        vec = _encode_cached("specter2-adhoc", texts, encoder.encode, cache_dir, batch_size)
        return DescSpace(model, normalise(vec))
    if model == "minilm":
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise MissingMlExtra("run `uv sync --extra ml`") from exc
        st = SentenceTransformer(MINILM, device=device)
        st.max_seq_length = min(st.max_seq_length, MAX_LENGTH)

        def encode(batch: list[str]) -> np.ndarray:
            return st.encode(batch, batch_size=batch_size, show_progress_bar=False)

        tv = _encode_cached("minilm", texts, encode, cache_dir, batch_size)
        wv = _encode_cached("minilm", [compose(p) for p in parts], encode, cache_dir, batch_size)
        return DescSpace(model, normalise(tv), normalise(wv))
    raise ValueError(f"unknown description model {model!r}; choose one of {MODELS}")
