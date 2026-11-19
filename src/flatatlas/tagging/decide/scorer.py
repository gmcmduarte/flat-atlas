"""``Scorer``: ask a model a question with fixed options, get one probability per option.

``score(prompt, options)`` runs one forward pass and returns the probabilities of the options'
first tokens, renormalised over the options. Options must be single tokens (letters, "Yes", "No"),
so there is nothing to sample and nothing to generate. Two implementations:

- ``LlamaScorer``: a local GGUF file through ``llama-cpp-python`` (optional ``llm`` extra). It keeps
  the key-value cache of the last prompt, so the part shared with the next prompt is not
  recomputed (put the shared text first).
- ``FakeScorer``: deterministic, for tests and CI. It never loads a model.
"""

from __future__ import annotations

import hashlib
import resource
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np


class MissingLlmExtra(RuntimeError):
    """``llama-cpp-python`` or the model file is not there."""


class Scorer(Protocol):
    def score(self, prompt: str, options: Sequence[str]) -> np.ndarray:
        """Probabilities of ``options`` (sum 1, same order) as the next token after ``prompt``."""
        ...


@dataclass
class ScorerStats:
    calls: int = 0
    prompt_tokens: int = 0  # tokens of all prompts
    evaluated_tokens: int = 0  # tokens actually run (the rest came from the cache)
    seconds: float = 0.0

    def snapshot(self) -> ScorerStats:
        return ScorerStats(self.calls, self.prompt_tokens, self.evaluated_tokens, self.seconds)

    def since(self, before: ScorerStats) -> ScorerStats:
        return ScorerStats(
            self.calls - before.calls,
            self.prompt_tokens - before.prompt_tokens,
            self.evaluated_tokens - before.evaluated_tokens,
            self.seconds - before.seconds,
        )


def peak_memory_mb() -> float:
    """Peak resident memory of this process (macOS reports bytes, Linux kilobytes)."""
    import sys

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


@dataclass
class FakeScorer:
    """Deterministic scores from a hash of (prompt, option); ``bias_first`` favours option 0.

    Used in tests: it records every call, so a test can assert that a cache hit made none.
    """

    bias_first: float = 0.0
    scale: float = 1.0
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    stats: ScorerStats = field(default_factory=ScorerStats)

    def score(self, prompt: str, options: Sequence[str]) -> np.ndarray:
        self.calls.append((prompt, tuple(options)))
        self.stats.calls += 1
        self.stats.prompt_tokens += len(prompt.split())
        self.stats.evaluated_tokens += len(prompt.split())
        logits = np.array(
            [
                self.scale
                * (
                    int.from_bytes(hashlib.sha256(f"{prompt}|{o}".encode()).digest()[:4], "big")
                    / 2**32
                )
                for o in options
            ]
        )
        logits[0] += self.bias_first
        e = np.exp(logits - logits.max())
        return e / e.sum()


def file_sha256(path: Path) -> str:
    """SHA-256 of a file, remembered in ``<file>.sha256`` (checked against size and mtime)."""
    side = path.with_name(path.name + ".sha256")
    st = path.stat()
    stamp = f"{st.st_size}:{int(st.st_mtime)}"
    if side.exists():
        digest, _, old = side.read_text(encoding="utf-8").strip().partition(" ")
        if old == stamp:
            return digest
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 24), b""):
            h.update(block)
    side.write_text(f"{h.hexdigest()} {stamp}\n", encoding="utf-8")
    return h.hexdigest()


class LlamaScorer:
    """A local GGUF model through llama.cpp. Loads from ``model_path`` only; no download."""

    def __init__(self, model_path: Path, *, n_ctx: int = 4096, n_threads: int | None = None):
        try:
            import llama_cpp
        except ImportError as exc:
            raise MissingLlmExtra("run `uv sync --extra llm` (llama-cpp-python)") from exc
        if not model_path.exists():
            raise MissingLlmExtra(f"model file not found: {model_path}")
        self.runtime = f"llama-cpp-python {llama_cpp.__version__}"
        kwargs = {} if n_threads is None else {"n_threads": n_threads}
        self.llm = llama_cpp.Llama(
            model_path=str(model_path),
            n_ctx=n_ctx,
            n_gpu_layers=-1,
            logits_all=False,
            verbose=False,
            **kwargs,
        )
        self.stats = ScorerStats()
        self._tokens: list[int] = []  # what the context currently holds
        self._option_ids: dict[str, int] = {}

    def _option_id(self, option: str) -> int:
        if option not in self._option_ids:
            ids = self.llm.tokenize(option.encode("utf-8"), add_bos=False, special=False)
            if len(ids) != 1:
                raise ValueError(f"option {option!r} is {len(ids)} tokens; options must be one")
            self._option_ids[option] = int(ids[0])
        return self._option_ids[option]

    def score(self, prompt: str, options: Sequence[str]) -> np.ndarray:
        t0 = time.perf_counter()
        ids = [self._option_id(o) for o in options]
        if len(set(ids)) != len(ids):
            raise ValueError("two options share a first token")
        tokens = [
            int(t) for t in self.llm.tokenize(prompt.encode("utf-8"), add_bos=False, special=True)
        ]
        # keep the longest shared prefix in the key-value cache, but always run the last token
        common = 0
        for a, b in zip(self._tokens, tokens[:-1], strict=False):
            if a != b:
                break
            common += 1
        self.llm.n_tokens = common
        self.llm.eval(tokens[common:])
        self._tokens = tokens
        logits = np.asarray(self.llm.scores[self.llm.n_tokens - 1], dtype=np.float64)
        chosen = logits[ids]
        e = np.exp(chosen - chosen.max())
        self.stats.calls += 1
        self.stats.prompt_tokens += len(tokens)
        self.stats.evaluated_tokens += len(tokens) - common
        self.stats.seconds += time.perf_counter() - t0
        return e / e.sum()
