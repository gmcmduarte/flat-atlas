"""Schemas of ``taxonomy/topics.yaml``, the proposals and ``taxonomy/gold.yaml`` (PLAN §9.1, §9.6).

Both files are human-edited and versioned in git (CLAUDE.md rule 5). The models here only say
what a *well-formed* file looks like; ``check.py`` holds the rules that need more than one entry
(cycles, shared phrases, the split rule, ...).

A topic's **level** is its shortest distance to a root: a topic with ``parents: []`` is a root and
has level 0; a child of a root has level 1; a topic with several parents takes the smallest level
(D-80). Phrases (``include_phrases``, ``exclude_phrases`` and ``aliases``) are plain strings, or
``{phrase: "...", context: ["word", ...]}`` when the phrase is ambiguous and a context word must
appear near it (PLAN §9.2).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import deque
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TOPIC_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MSC_CODE = re.compile(r"^\d{2}[A-Z]\d{2}$")
CCS_ID = re.compile(r"^\d{5,10}(?:\.\d{5,10})*$")
WORK_ID = re.compile(r"^W[0-9A-Z]{10,26}$")

Origin = Literal["ccs", "msc", "mined", "cluster", "manual"]
Status = Literal["active", "proposed", "deprecated"]
Split = Literal["train", "heldout"]
Sampling = Literal["random", "topup"]

SPLIT_SALT = "gold-split-v1"
HELDOUT_MODULUS = 3  # one work in three is held out


def normalise_phrase(text: str) -> str:
    """Lower case, accents and hyphens folded, white space collapsed: the key phrases compare by."""
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = re.sub(r"[-_/]+", " ", folded.casefold())
    folded = re.sub(r"[^\w\s]+", "", folded)
    return re.sub(r"\s+", " ", folded).strip()


def split_for(work_id: str) -> Split:
    """The split of a labelled work, a function of its ID only (PLAN §9.6, D-80).

    One third of the IDs (hash value modulo 3 equal to 0) are held out. Written once, here, so the
    loader, ``taxonomy check`` and the labelling tools can never disagree.
    """
    digest = hashlib.sha256(f"{SPLIT_SALT}:{work_id}".encode()).digest()
    return "heldout" if int.from_bytes(digest[:8], "big") % HELDOUT_MODULUS == 0 else "train"


class PhraseWithContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phrase: str = Field(min_length=1)
    context: list[str] = Field(default_factory=list)


Phrase = str | PhraseWithContext


def phrase_text(phrase: Phrase) -> str:
    return phrase if isinstance(phrase, str) else phrase.phrase


def phrase_has_context(phrase: Phrase) -> bool:
    return not isinstance(phrase, str) and bool(phrase.context)


class Xref(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ccs: list[str] = Field(default_factory=list)
    msc: list[str] = Field(default_factory=list)
    openalex: list[str] = Field(default_factory=list)

    @field_validator("msc")
    @classmethod
    def _msc_codes(cls, codes: list[str]) -> list[str]:
        bad = [c for c in codes if not MSC_CODE.match(c)]
        if bad:
            raise ValueError(f"not MSC2020 codes: {bad}")
        return codes

    @field_validator("ccs")
    @classmethod
    def _ccs_ids(cls, ids: list[str]) -> list[str]:
        bad = [c for c in ids if not CCS_ID.match(c)]
        if bad:
            raise ValueError(f"not CCS concept ids (digits, dot-separated): {bad}")
        return ids


class TopicEntry(BaseModel):
    """One topic, exactly the entry format of PLAN §9.1 (plus ``status`` and proposal fields)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    parents: list[str] = Field(default_factory=list)
    xref: Xref = Field(default_factory=Xref)
    include_phrases: list[Phrase] = Field(default_factory=list)
    exclude_phrases: list[Phrase] = Field(default_factory=list)
    seed_works: list[str] = Field(default_factory=list)  # work IDs or DOIs
    origin: Origin
    reviewed: bool = False
    status: Status = "active"
    # Proposal files only: counts and reasons behind the topic. Ignored by the pipeline.
    evidence: dict[str, Any] | None = None

    @field_validator("id")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not TOPIC_ID.match(value):
            raise ValueError("a topic id is a lower-case slug: letters, digits and single hyphens")
        return value

    @model_validator(mode="after")
    def _no_self_parent(self) -> TopicEntry:
        if self.id in self.parents:
            raise ValueError("a topic cannot be its own parent")
        if len(set(self.parents)) != len(self.parents):
            raise ValueError("duplicate parent")
        return self


class TopicsFile(BaseModel):
    """``taxonomy/topics.yaml`` and ``taxonomy/proposals/vN.yaml``."""

    model_config = ConfigDict(extra="forbid")

    taxonomy_version: int = Field(ge=1)
    topics: list[TopicEntry]

    def by_id(self) -> dict[str, TopicEntry]:
        return {t.id: t for t in self.topics}


def topic_levels(topics: list[TopicEntry]) -> dict[str, int]:
    """Shortest distance to a root, for every topic that reaches one (unknown parents ignored)."""
    by_id = {t.id: t for t in topics}
    children: dict[str, list[str]] = {}
    for t in topics:
        for parent in t.parents:
            if parent in by_id:
                children.setdefault(parent, []).append(t.id)
    levels = {t.id: 0 for t in topics if not t.parents}
    queue = deque(sorted(levels))
    while queue:
        current = queue.popleft()
        for child in children.get(current, []):
            if child not in levels:
                levels[child] = levels[current] + 1
                queue.append(child)
    return levels


class GoldWork(BaseModel):
    """One labelled work (PLAN §9.6)."""

    model_config = ConfigDict(extra="forbid")

    work: str
    title: str = ""  # for the reader; not authoritative
    labels: list[str] = Field(default_factory=list)  # level 0 and 1, every one that applies
    split: Split
    sampling: Sampling = "random"
    blind: bool = False
    reviewed: bool = False
    note: str = ""

    @field_validator("work")
    @classmethod
    def _work_id(cls, value: str) -> str:
        if not WORK_ID.match(value):
            raise ValueError("not an Atlas work ID (W plus 10 or more base32 characters)")
        return value


class GoldFile(BaseModel):
    """``taxonomy/gold.yaml``."""

    model_config = ConfigDict(extra="forbid")

    taxonomy_version: int = Field(ge=1)
    works: list[GoldWork]
