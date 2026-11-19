"""The two questions of the decision model, as versioned prompt builders (PLAN §9.5).

*Choice*: which of the level-0 topics fits the paper best? The options are letters, listed in one
of a few fixed orders (the model's bias towards early options is averaged away). The instructions
and the option list come first and are identical for every work, so the runtime can keep their
key-value cache; the paper text comes last.

*Yes/no*: does this one topic fit the paper? The instructions and the paper come first (every
question about one work shares them) and the topic last.

The paper text is the composite text of P1-05 (``CompositeParts.text``). It may contain an
abstract or a TLDR: prompts are local, never exported (hard rule 2).

Bump ``PROMPT_VERSION`` when the wording changes. The answer cache also stores a hash of the exact
prompt, so a changed topic description cannot serve a stale answer.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

PROMPT_VERSION = "dm-1"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
YES, NO = "Yes", "No"
YESNO_OPTIONS = (YES, NO)

_SYSTEM = (
    "You are an expert in formal languages and automata theory and you classify research papers "
    "by topic."
)
_CHOICE_INTRO = (
    "Here are the main research areas of formal languages and automata theory, each with a letter."
)
_YESNO_INTRO = (
    "You will read a short description of a research paper and then a research area of formal "
    "languages and automata theory. Decide whether the area fits the paper: whether the paper "
    "is about that area, not merely close to it."
)


@dataclass(frozen=True)
class Topic:
    id: str
    name: str
    description: str


def one_line(description: str, limit: int = 200) -> str:
    """The first sentence of a description, cut at a word boundary after ``limit`` characters."""
    flat = re.sub(r"\s+", " ", description).strip()
    m = re.match(r"(.+?[.!?])(\s|$)", flat)
    first = m.group(1) if m else flat
    if len(first) <= limit:
        return first
    cut = first[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def chatml(user: str) -> str:
    """Qwen3's chat format with thinking switched off (an empty think block is pre-filled)."""
    return (
        f"<|im_start|>system\n{_SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )


def option_orders(n_options: int, n_orders: int) -> list[tuple[int, ...]]:
    """Fixed orders of the options: as listed, reversed, then a fixed hash shuffle.

    ``order[position] = option index``. The same orders for every work and every run.
    """
    if not 1 <= n_orders <= 3:
        raise ValueError("option_orders must be 1, 2 or 3")
    base = tuple(range(n_options))
    shuffled = tuple(
        sorted(base, key=lambda i: hashlib.sha256(f"dm-order-3:{i}".encode()).digest())
    )
    return [base, tuple(reversed(base)), shuffled][:n_orders]


def choice_options(n: int) -> tuple[str, ...]:
    if n > len(LETTERS):
        raise ValueError(f"at most {len(LETTERS)} options")
    return tuple(LETTERS[:n])


def choice_prefix(topics: Sequence[Topic], order: Sequence[int]) -> str:
    """Instructions and the option list: identical for every work, for a given order."""
    lines = [
        f"{LETTERS[pos]}. {topics[i].name}: {one_line(topics[i].description)}"
        for pos, i in enumerate(order)
    ]
    return (
        f"{_CHOICE_INTRO}\n\n" + "\n".join(lines) + "\n\n"
        "You will read a short description of a research paper. Choose the area that fits it best."
        "\n\nPaper:\n"
    )


def choice_prompt(text: str, topics: Sequence[Topic], order: Sequence[int]) -> str:
    user = (
        choice_prefix(topics, order)
        + text.strip()
        + "\n\nWhich area fits this paper best? Reply with one letter only."
    )
    return chatml(user)


def yesno_prompt(text: str, topic: Topic) -> str:
    user = (
        f"{_YESNO_INTRO}\n\nPaper:\n{text.strip()}\n\n"
        f"Area: {topic.name}. {topic.description.strip()}\n\n"
        "Does this area fit the paper? Reply with Yes or No only."
    )
    return chatml(user)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def by_topic(order: Sequence[int], probs_by_position: np.ndarray) -> np.ndarray:
    """Option probabilities by position -> by option index (undo the shuffle)."""
    out = np.zeros(len(order))
    for pos, i in enumerate(order):
        out[i] = probs_by_position[pos]
    return out


def average(per_order: Sequence[np.ndarray]) -> np.ndarray:
    """Mean over the orders of probabilities indexed by option (renormalised)."""
    m = np.mean(np.vstack(per_order), axis=0)
    return m / m.sum()
