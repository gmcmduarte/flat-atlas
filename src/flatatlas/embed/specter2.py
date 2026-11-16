"""Local SPECTER2 embeddings for papers Semantic Scholar has no vector for (P1-03).

Model (from the model card, checked 2026-11-16): base ``allenai/specter2_base`` plus the
*proximity* adapter ``allenai/specter2`` (the adapter was renamed on Hugging Face; the old
``specter2_proximity`` name is gone), loaded with the ``adapters`` library. The vector is the
first-token (CLS) state of the last layer, 768 floats. Input is ``title [SEP] abstract``.

Everything that needs torch is imported lazily inside ``load_encoder`` so that the base install,
the base CI job and the tests never import it (``uv sync --extra ml`` installs it).

``embed_texts`` is the batching and resume logic and works with any ``Encoder``. Finished batches
are written to a small on-disk cache keyed by (model, text), so a killed job loses at most one
batch and a re-run with the same inputs computes nothing.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from flatatlas.embed.store import DIM

log = logging.getLogger(__name__)

BASE_MODEL = "allenai/specter2_base"
ADAPTER = "allenai/specter2"
ADAPTER_NAME = "proximity"
MODEL_LABEL = f"{BASE_MODEL}+{ADAPTER}({ADAPTER_NAME})"
MAX_LENGTH = 512
DEFAULT_SEP = "[SEP]"


class MissingMlExtra(RuntimeError):
    """torch, transformers or adapters is not installed."""


class Encoder(Protocol):
    """Turns texts into an ``(n, 768)`` float32 array."""

    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


def format_input(
    title: str, abstract: str | None, sep: str = DEFAULT_SEP, *, sep_when_empty: bool = False
) -> tuple[str, str]:
    """The text to embed and its kind: ``title+abstract`` or ``title``.

    The model card builds ``title + sep + (abstract or '')``, which keeps a trailing separator for
    papers without an abstract. P1-03's rule is the title alone in that case; ``sep_when_empty``
    gives the card's variant so ``embed compare`` can measure which one matches Semantic Scholar's
    vectors.
    """
    title = " ".join((title or "").split())
    abstract = " ".join((abstract or "").split())
    if abstract:
        return f"{title}{sep}{abstract}", "title+abstract"
    return (f"{title}{sep}" if sep_when_empty else title), "title"


# -- the real encoder (torch) ----------------------------------------------------------------------


def resolve_device(requested: str) -> str:
    """``mps`` or ``cuda`` when available, else ``cpu`` (with a warning)."""
    try:
        import torch
    except ImportError as exc:
        raise MissingMlExtra("torch is not installed: run `uv sync --extra ml`") from exc
    if requested == "mps" and not torch.backends.mps.is_available():
        log.warning("device mps is not available; using cpu")
        return "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        log.warning("device cuda is not available; using cpu")
        return "cpu"
    return requested


class Specter2Encoder:
    """SPECTER2 (base + proximity adapter) on one device. Loading it downloads the model once."""

    def __init__(self, device: str = "cpu") -> None:
        try:
            import torch
            from adapters import AutoAdapterModel
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise MissingMlExtra(
                "torch, transformers and adapters are needed: run `uv sync --extra ml`"
            ) from exc
        self._torch = torch
        self.device = resolve_device(device)
        self.tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
        model = AutoAdapterModel.from_pretrained(BASE_MODEL)
        model.load_adapter(ADAPTER, source="hf", load_as=ADAPTER_NAME, set_active=True)
        self.model = model.to(self.device).eval()
        if not self.model.active_adapters:  # a silent fallback to the plain base model
            raise RuntimeError(f"the {ADAPTER_NAME!r} adapter did not become active")
        self.sep = self.tokenizer.sep_token or DEFAULT_SEP

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        torch = self._torch
        inputs = self.tokenizer(
            list(texts),
            padding=True,
            truncation=True,
            return_tensors="pt",
            return_token_type_ids=False,
            max_length=MAX_LENGTH,
        ).to(self.device)
        with torch.no_grad():
            out = self.model(**inputs)
        vectors = out.last_hidden_state[:, 0, :].float().cpu().numpy()
        if vectors.shape[1] != DIM:
            raise RuntimeError(f"model returned {vectors.shape[1]} dimensions, expected {DIM}")
        return vectors.astype(np.float32)


def load_encoder(device: str = "cpu") -> Specter2Encoder:
    return Specter2Encoder(device)


# -- batching and resume -------------------------------------------------------------------------


def text_hash(text: str, model: str = MODEL_LABEL) -> str:
    return hashlib.sha256(f"{model}\x00{text}".encode()).hexdigest()


class VectorCache:
    """Finished batches on disk: one ``.npz`` per batch with ``hashes`` and ``vectors``."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def load(self) -> dict[str, np.ndarray]:
        found: dict[str, np.ndarray] = {}
        for path in sorted(self.folder.glob("*.npz")):
            try:
                with np.load(path) as shard:
                    hashes, vectors = shard["hashes"], shard["vectors"]
                for h, v in zip(hashes.tolist(), vectors, strict=True):
                    found[str(h)] = v
            except (OSError, ValueError, KeyError):
                continue  # corrupt shard: those texts are simply computed again
        return found

    def save(self, hashes: Sequence[str], vectors: np.ndarray) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha1("".join(hashes).encode()).hexdigest()[:16]  # noqa: S324 - not security
        final = self.folder / f"{name}.npz"
        tmp = self.folder / f".{name}.{uuid.uuid4().hex}.tmp.npz"
        try:
            np.savez(tmp, hashes=np.array(list(hashes)), vectors=vectors.astype(np.float32))
            os.replace(tmp, final)
        finally:
            tmp.unlink(missing_ok=True)


@dataclass
class EmbedStats:
    texts: int = 0
    from_cache: int = 0
    computed: int = 0
    batches: int = 0
    seconds: float = 0.0  # time spent in the encoder only

    @property
    def per_second(self) -> float:
        return self.computed / self.seconds if self.seconds > 0 else 0.0


def embed_texts(
    texts: Sequence[str],
    encoder: Encoder,
    *,
    batch_size: int,
    cache: VectorCache | None = None,
    on_progress: Callable[[str], None] | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[np.ndarray, EmbedStats]:
    """Vectors for ``texts`` in input order. Texts in the cache are not computed again.

    Missing texts are sorted by length so a batch pads little, computed ``batch_size`` at a time,
    and each finished batch is saved before the next starts (resume). Equal texts are computed once.
    """
    say = on_progress or (lambda _msg: None)
    stats = EmbedStats(texts=len(texts))
    hashes = [text_hash(t) for t in texts]
    have = cache.load() if cache else {}
    todo = {h: t for h, t in zip(hashes, texts, strict=True) if h not in have}
    stats.from_cache = len(texts) - sum(1 for h in hashes if h in todo)

    ordered = sorted(todo, key=lambda h: (len(todo[h]), h))
    for start in range(0, len(ordered), max(batch_size, 1)):
        chunk = ordered[start : start + batch_size]
        t0 = clock()
        vectors = np.asarray(encoder.encode([todo[h] for h in chunk]), dtype=np.float32)
        stats.seconds += clock() - t0
        if vectors.shape != (len(chunk), DIM):
            raise RuntimeError(
                f"encoder returned shape {vectors.shape}, expected {(len(chunk), DIM)}"
            )
        if cache:
            cache.save(chunk, vectors)
        for h, v in zip(chunk, vectors, strict=True):
            have[h] = v
        stats.batches += 1
        stats.computed += len(chunk)
        say(f"embedded {min(start + batch_size, len(ordered))}/{len(ordered)} texts")
    out = np.vstack([have[h] for h in hashes]) if hashes else np.zeros((0, DIM), dtype=np.float32)
    return out, stats
