"""Atlas IDs and the ID registry (PLAN §4.1).

An Atlas ID is a one-letter kind prefix plus base32 characters taken from a hash of the *anchor*,
the ``(source, id)`` pair that first identified the thing: ``W`` works, ``A`` authors, ``V``
venues, ``E`` editions. The same anchor always gives the same ID. The registry is authoritative:

- an ID is never reused: a merged-away ID stays in the table with ``merged_into`` set;
- if the hash of a new anchor collides with an existing ID, the new ID takes one more character
  (the registry is part of every release, so the outcome is stable across rebuilds);
- ``resolve()`` follows ``merged_into`` to the surviving ID.

The registry is a Parquet file, ``core_id_registry.parquet`` in the warehouse folder.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Literal

import pyarrow as pa
import pyarrow.parquet as pq

from flatatlas.db import utcnow, write_parquet_atomic
from flatatlas.settings import Paths

Kind = Literal["work", "author", "venue", "edition"]

PREFIX: dict[str, str] = {"work": "W", "author": "A", "venue": "V", "edition": "E"}
KIND_OF_PREFIX = {prefix: kind for kind, prefix in PREFIX.items()}

# 10 base32 characters = 50 bits: about a 4 in 100,000 chance of any collision among 300,000 IDs.
BASE_LENGTH = 10
MAX_LENGTH = 26

# PLAN §4.1: DBLP key, then DOI, then OpenAlex, then Semantic Scholar, then zbMATH.
ANCHOR_PREFERENCE = ("dblp", "doi", "openalex", "s2", "zbmath")

REGISTRY_FILE = "core_id_registry.parquet"

SCHEMA = pa.schema(
    [
        ("atlas_id", pa.string()),
        ("kind", pa.string()),
        ("anchor_source", pa.string()),
        ("anchor_id", pa.string()),
        ("minted_at", pa.timestamp("us")),
        ("merged_into", pa.string()),
    ]
)

_DOI_PREFIX = re.compile(r"^(https?://(dx\.)?doi\.org/|doi:)", re.IGNORECASE)


class RegistryError(ValueError):
    """An invalid registry operation (unknown ID, kind mismatch, cycle, ...)."""


def normalise_anchor(source: str, anchor_id: str) -> tuple[str, str]:
    """Canonical form of an anchor, so that spelling variants give the same ID."""
    source = source.strip().lower()
    anchor_id = anchor_id.strip()
    if not source or not anchor_id:
        raise RegistryError("an anchor needs a source and an id")
    if source == "doi":
        anchor_id = _DOI_PREFIX.sub("", anchor_id).lower()
    return source, anchor_id


def mint_id(kind: Kind, source: str, anchor_id: str, *, length: int = BASE_LENGTH) -> str:
    """The ID for an anchor, ignoring collisions (pure function; the registry handles those)."""
    source, anchor_id = normalise_anchor(source, anchor_id)
    digest = hashlib.sha256(f"{kind}\x1f{source}\x1f{anchor_id}".encode()).digest()
    text = base64.b32encode(digest).decode("ascii").rstrip("=")
    return PREFIX[kind] + text[:length]


def choose_anchor(anchors: Mapping[str, str]) -> tuple[str, str]:
    """The preferred anchor of ``{source: id}`` (PLAN §4.1 order)."""
    for source in ANCHOR_PREFERENCE:
        if anchors.get(source):
            return source, anchors[source]
    raise RegistryError(f"no usable anchor among {sorted(anchors)}")


@dataclass(frozen=True)
class Entry:
    atlas_id: str
    kind: str
    anchor_source: str
    anchor_id: str
    minted_at: datetime
    merged_into: str | None = None


class IdRegistry:
    """The ID table in memory. ``load()`` and ``save()`` move it to and from Parquet."""

    def __init__(self, entries: list[Entry] | None = None) -> None:
        self._by_id: dict[str, Entry] = {}
        self._by_anchor: dict[tuple[str, str, str], str] = {}
        for entry in entries or []:
            self._add(entry)

    # -- persistence --------------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path | Paths) -> IdRegistry:
        """Read the registry; a missing file is an empty registry."""
        file = _registry_path(path)
        if not file.exists():
            return cls()
        rows = pq.read_table(file).to_pylist()
        return cls([Entry(**row) for row in rows])

    def save(self, path: Path | Paths) -> Path:
        rows = [vars(e) for e in sorted(self._by_id.values(), key=lambda e: e.atlas_id)]
        table = pa.Table.from_pylist(rows, schema=SCHEMA)
        return write_parquet_atomic(table, _registry_path(path))

    # -- minting ------------------------------------------------------------------------------

    def get_or_mint(
        self,
        kind: Kind,
        source: str,
        anchor_id: str,
        *,
        now: Callable[[], datetime] = utcnow,
    ) -> str:
        """The ID of an anchor: the existing one, or a new one. Never changes once minted."""
        source, anchor_id = normalise_anchor(source, anchor_id)
        existing = self._by_anchor.get((kind, source, anchor_id))
        if existing is not None:
            return existing
        for length in range(BASE_LENGTH, MAX_LENGTH + 1):
            candidate = mint_id(kind, source, anchor_id, length=length)
            if candidate not in self._by_id:
                self._add(Entry(candidate, kind, source, anchor_id, now()))
                return candidate
        raise RegistryError(f"could not mint a free ID for {kind} {source}:{anchor_id}")

    def mint_from(
        self,
        kind: Kind,
        anchors: Mapping[str, str],
        *,
        now: Callable[[], datetime] = utcnow,
    ) -> str:
        """The ID for a thing known by several anchors.

        If one of the anchors was already minted, its ID is returned (an ID never changes just
        because a better anchor appeared later). Otherwise the preferred anchor is minted. Only
        the minted anchor is stored; linking a work to its other identifiers is the job of the
        resolve stage, which uses ``merge`` when two minted IDs turn out to be one thing.
        """
        existing = {
            self._by_anchor[(kind, *normalise_anchor(s, a))]
            for s, a in anchors.items()
            if a and (kind, *normalise_anchor(s, a)) in self._by_anchor
        }
        if len(existing) == 1:
            return next(iter(existing))
        if len(existing) > 1:
            raise RegistryError(
                f"anchors point to different IDs {sorted(existing)}: merge them explicitly"
            )
        source, anchor_id = choose_anchor(anchors)
        return self.get_or_mint(kind, source, anchor_id, now=now)

    # -- merging and lookup -------------------------------------------------------------------

    def merge(self, loser: str, winner: str) -> str:
        """Redirect ``loser`` to ``winner`` (or to whatever ``winner`` has itself become).

        Returns the surviving ID. Merging an ID into itself, across kinds, or into a chain that
        leads back to ``loser`` is refused. Repeating a merge that already holds is harmless.
        """
        loser_entry = self._entry(loser)
        survivor = self.resolve(winner)
        if loser_entry.kind != self._entry(survivor).kind:
            raise RegistryError(f"cannot merge {loser} and {survivor}: different kinds")
        if survivor == loser:
            # ``survivor`` is a root, so ``loser`` is one too: merging would make a cycle.
            raise RegistryError(f"cannot merge {loser} into itself or into an ID that leads to it")
        if loser_entry.merged_into is not None and self.resolve(loser) != survivor:
            raise RegistryError(
                f"{loser} is already merged into {loser_entry.merged_into}; merge that ID instead"
            )
        self._by_id[loser] = replace(loser_entry, merged_into=survivor)
        return survivor

    def resolve(self, atlas_id: str) -> str:
        """Follow ``merged_into`` redirects to the surviving ID."""
        seen = {atlas_id}
        current = self._entry(atlas_id)
        while current.merged_into is not None:
            if current.merged_into in seen:
                raise RegistryError(f"redirect cycle at {current.merged_into}")
            seen.add(current.merged_into)
            current = self._entry(current.merged_into)
        return current.atlas_id

    def lookup(self, kind: Kind, source: str, anchor_id: str) -> str | None:
        """The ID of an anchor if it was minted, else None (does not mint)."""
        return self._by_anchor.get((kind, *normalise_anchor(source, anchor_id)))

    def entry(self, atlas_id: str) -> Entry:
        return self._entry(atlas_id)

    def __contains__(self, atlas_id: object) -> bool:
        return atlas_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    # -- internals ----------------------------------------------------------------------------

    def _entry(self, atlas_id: str) -> Entry:
        try:
            return self._by_id[atlas_id]
        except KeyError:
            raise RegistryError(f"unknown atlas ID {atlas_id!r}") from None

    def _add(self, entry: Entry) -> None:
        if entry.atlas_id in self._by_id:
            raise RegistryError(f"duplicate atlas ID {entry.atlas_id}")
        key = (entry.kind, entry.anchor_source, entry.anchor_id)
        if key in self._by_anchor:
            raise RegistryError(f"anchor {key} already has an ID")
        self._by_id[entry.atlas_id] = entry
        self._by_anchor[key] = entry.atlas_id


def _registry_path(path: Path | Paths) -> Path:
    if isinstance(path, Paths):
        return path.warehouse / REGISTRY_FILE
    return Path(path)
