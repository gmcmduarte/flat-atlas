"""The venue registry: ``config/venues.yaml`` and ``config/venue_facts.yaml`` (PLAN §7, §8.4).

Adding a venue is a config change (CLAUDE.md rule 9). This module loads and validates the files;
it never touches the network.

``config/venues.yaml`` is a list of entries. ``successor_of`` lists the venue(s) this one
continues (``ciaa`` has ``successor_of: [wia]``). ``verified`` records, per source, the date on
which the entry's identifiers were checked against the live source; ``null`` means the value
still comes from memory and must not be relied on.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from flatatlas.settings import CONFIG_DIR

VENUES_FILE = CONFIG_DIR / "venues.yaml"
VENUE_FACTS_FILE = CONFIG_DIR / "venue_facts.yaml"

Kind = Literal["conference", "journal", "book-series"]
Tier = Literal["core", "broad", "other"]

VenueId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]*$")]
OpenAlexSourceId = Annotated[str, Field(pattern=r"^S\d+$")]
Issn = Annotated[str, Field(pattern=r"^\d{4}-\d{3}[\dX]$")]


class VenueConfigError(ValueError):
    """The venue files are invalid. ``problems`` lists every problem found, not just the first."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("\n".join(problems))


class CoreRank(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | None = None
    edition: str | None = None
    source_url: str | None = None


class Verified(BaseModel):
    """Date each source was last checked for this entry (``null`` = not verified)."""

    model_config = ConfigDict(extra="forbid")

    dblp: date | None = None  # dblp_stream, first_year, predecessor links
    openalex: date | None = None  # openalex_source_ids


class Venue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: VenueId
    acronym: str
    name: str
    kind: Kind
    tier: Tier
    dblp_stream: str | None = None  # e.g. conf/dlt, journals/iandc
    openalex_source_ids: list[OpenAlexSourceId] = []
    issn: list[Issn] = []
    publisher: str | None = None
    first_year: int | None = Field(None, ge=1900, le=2100)
    last_year: int | None = Field(None, ge=1900, le=2100)
    successor_of: list[VenueId] = []
    special_issue_of: VenueId | None = None
    expected_topics: list[str] = []  # topic slugs; checked once the taxonomy exists (P1-06)
    homepage: str | None = None
    core_rank: CoreRank = CoreRank()
    verified: Verified = Verified()
    notes: str = ""

    @property
    def is_verified(self) -> bool:
        return self.verified.dblp is not None and self.verified.openalex is not None


class VenueRegistry:
    """Validated venues, in file order."""

    def __init__(self, venues: list[Venue]) -> None:
        self.venues = venues
        self._by_id = {v.id: v for v in venues}

    def __iter__(self):
        return iter(self.venues)

    def __len__(self) -> int:
        return len(self.venues)

    def __contains__(self, venue_id: object) -> bool:
        return venue_id in self._by_id

    def get(self, venue_id: str) -> Venue:
        try:
            return self._by_id[venue_id]
        except KeyError:
            raise KeyError(f"Unknown venue {venue_id!r}") from None

    def ids(self) -> list[str]:
        return list(self._by_id)

    def predecessors(self, venue_id: str) -> list[str]:
        """All venues ``venue_id`` continues, transitively (nearest first, no duplicates)."""
        seen: list[str] = []
        queue = list(self.get(venue_id).successor_of)
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.append(current)
            queue.extend(self.get(current).successor_of)
        return seen

    def unverified(self) -> list[tuple[str, list[str]]]:
        """``(venue id, sources not yet verified)`` for every venue that is not fully verified."""
        out = []
        for venue in self.venues:
            missing = [s for s in ("dblp", "openalex") if getattr(venue.verified, s) is None]
            if missing:
                out.append((venue.id, missing))
        return out


def find_problems(venues: list[Venue]) -> list[str]:
    """Cross-entry checks: unique ids, known targets, no cycles, sane year ranges."""
    problems: list[str] = []
    ids = [v.id for v in venues]
    for venue_id in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"duplicate venue id {venue_id!r}")
    known = set(ids)

    for venue in venues:
        for target in venue.successor_of:
            if target not in known:
                problems.append(f"{venue.id}: successor_of names unknown venue {target!r}")
            elif target == venue.id:
                problems.append(f"{venue.id}: successor_of names itself")
        if venue.special_issue_of is not None and venue.special_issue_of not in known:
            problems.append(f"{venue.id}: special_issue_of names unknown venue")
        if venue.first_year and venue.last_year and venue.last_year < venue.first_year:
            problems.append(f"{venue.id}: last_year {venue.last_year} < first_year")
        if venue.verified.dblp and not venue.dblp_stream:
            problems.append(f"{venue.id}: verified.dblp is set but dblp_stream is empty")
        if venue.verified.openalex and not venue.openalex_source_ids:
            problems.append(
                f"{venue.id}: verified.openalex is set but openalex_source_ids is empty"
            )

    # Two venues may share one DBLP stream (WIA and CIAA are both conf/wia) only if both state
    # a year range and the ranges do not overlap: the range decides which editions are whose.
    by_stream: dict[str, list[Venue]] = {}
    for venue in venues:
        if venue.dblp_stream:
            by_stream.setdefault(venue.dblp_stream, []).append(venue)
    for stream, sharing in by_stream.items():
        if len(sharing) < 2:
            continue
        names = ", ".join(v.id for v in sharing)
        if any(v.first_year is None for v in sharing):
            problems.append(f"{stream} is shared by {names}: each needs first_year")
            continue
        spans = sorted((v.first_year or 0, v.last_year or 9999, v.id) for v in sharing)
        for (_, end, a), (start, _, b) in zip(spans, spans[1:], strict=False):
            if start <= end:
                problems.append(f"{stream}: year ranges of {a} and {b} overlap")

    # Cycles in successor_of: depth-first search; a node met again while still on the path closes
    # a cycle.
    edges = {v.id: [t for t in v.successor_of if t in known and t != v.id] for v in venues}
    done: set[str] = set()

    def visit(node: str, path: list[str]) -> None:
        for nxt in edges[node]:
            if nxt in path:
                cycle = [*path[path.index(nxt) :], nxt]
                problems.append("successor_of cycle: " + " -> ".join(cycle))
            elif nxt not in done:
                visit(nxt, [*path, nxt])
        done.add(node)

    for node in edges:
        if node not in done:
            visit(node, [node])
    return problems


def _read_yaml(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _format_validation_error(label: str, exc: ValidationError) -> list[str]:
    return [
        f"{label}: {'.'.join(str(p) for p in err['loc']) or '(entry)'}: {err['msg']}"
        for err in exc.errors()
    ]


def parse_venues(raw: object) -> VenueRegistry:
    """Validate the content of ``venues.yaml`` (a list of mappings)."""
    if not isinstance(raw, list):
        raise VenueConfigError(["venues.yaml: expected a list of venue entries"])
    venues: list[Venue] = []
    problems: list[str] = []
    for index, item in enumerate(raw):
        label = item.get("id", f"entry {index}") if isinstance(item, dict) else f"entry {index}"
        try:
            venues.append(Venue.model_validate(item))
        except ValidationError as exc:
            problems.extend(_format_validation_error(str(label), exc))
    problems.extend(find_problems(venues))
    if problems:
        raise VenueConfigError(problems)
    return VenueRegistry(venues)


def load_venues(path: Path = VENUES_FILE) -> VenueRegistry:
    return parse_venues(_read_yaml(path))


# -- venue facts (PLAN §4.2 core_edition, §15.1) ------------------------------------------------


class Fact(BaseModel):
    """One manually sourced number or label. A value without a ``source_url`` is rejected."""

    model_config = ConfigDict(extra="forbid")

    value: int | str | None = None
    source_url: str | None = None
    note: str | None = None


class YearFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    core_rank: Fact = Fact()
    submissions: Fact = Fact()
    accepted: Fact = Fact()


class VenueFacts(BaseModel):
    """``config/venue_facts.yaml``: ``venues: {<venue id>: {<year>: YearFacts}}``."""

    model_config = ConfigDict(extra="forbid")

    venues: dict[str, dict[int, YearFacts]] = {}


def parse_venue_facts(raw: object, registry: VenueRegistry | None = None) -> VenueFacts:
    if raw is None:
        raw = {}
    problems: list[str] = []
    try:
        facts = VenueFacts.model_validate(raw)
    except ValidationError as exc:
        raise VenueConfigError(_format_validation_error("venue_facts.yaml", exc)) from None
    for venue_id, years in facts.venues.items():
        if registry is not None and venue_id not in registry:
            problems.append(f"venue_facts.yaml: unknown venue {venue_id!r}")
        for year, year_facts in years.items():
            if not 1900 <= year <= 2100:
                problems.append(f"venue_facts.yaml: {venue_id}: implausible year {year}")
            for name, fact in year_facts.model_dump().items():
                if fact["value"] is not None and not fact["source_url"]:
                    problems.append(
                        f"venue_facts.yaml: {venue_id} {year} {name}: a value needs a source_url"
                    )
    if problems:
        raise VenueConfigError(problems)
    return facts


def load_venue_facts(
    path: Path = VENUE_FACTS_FILE, registry: VenueRegistry | None = None
) -> VenueFacts:
    return parse_venue_facts(_read_yaml(path), registry)


def profile_problems(registry: VenueRegistry, config_dir: Path = CONFIG_DIR) -> list[str]:
    """Profiles may only activate venues that exist (``active_venues: all`` is always fine)."""
    problems = []
    for file in sorted((config_dir / "profiles").glob("*.yaml")):
        active = (_read_yaml(file) or {}).get("active_venues", [])
        if active == "all":
            continue
        problems.extend(
            f"profiles/{file.name}: active_venues names unknown venue {v!r}"
            for v in active
            if v not in registry
        )
    return problems
