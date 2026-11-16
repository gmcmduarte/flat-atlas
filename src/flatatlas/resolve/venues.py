"""``core_venue`` and ``core_edition`` (PLAN §4.2): the registry plus DBLP's edition rows."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from flatatlas.venues import VenueFacts, VenueRegistry

Row = Mapping[str, Any]


def build_venue_rows(
    registry: VenueRegistry, mint_venue: Callable[[str], str]
) -> list[dict[str, Any]]:
    """One row per venue of ``venues.yaml``; ``successor_of`` is translated to Atlas IDs."""
    rows = []
    for venue in registry:
        rows.append(
            {
                "venue_id": mint_venue(venue.id),
                "acronym": venue.acronym,
                "name": venue.name,
                "kind": venue.kind,
                "tier": venue.tier,
                "dblp_stream": venue.dblp_stream,
                "openalex_source_ids": list(venue.openalex_source_ids),
                "issn": list(venue.issn),
                "publisher": venue.publisher,
                "first_year": venue.first_year,
                "last_year": venue.last_year,
                "successor_of": sorted(mint_venue(v) for v in venue.successor_of),
                "homepage": venue.homepage,
            }
        )
    rows.sort(key=lambda r: r["venue_id"])
    return rows


def build_edition_rows(
    editions: Iterable[Row],
    *,
    venue_atlas_id: Mapping[str, str],
    mint_edition: Callable[[str], str],
    facts: VenueFacts | None = None,
) -> list[dict[str, Any]]:
    """One row per edition of ``stg_dblp_edition``.

    The manually sourced facts (``config/venue_facts.yaml``) fill ``submissions`` and ``accepted``
    when the file has them for that venue and year; the rate is computed, never typed.
    """
    rows = []
    for edition in editions:
        venue_config_id = edition["venue_id"]
        year_facts = ((facts.venues.get(venue_config_id) or {}) if facts else {}).get(
            int(edition["year"])
        )
        submissions = accepted = None
        source_url = source_note = None
        if year_facts is not None:
            submissions = _int_or_none(year_facts.submissions.value)
            accepted = _int_or_none(year_facts.accepted.value)
            source = year_facts.accepted if accepted is not None else year_facts.submissions
            source_url, source_note = source.source_url, source.note
        rate = accepted / submissions if submissions and accepted is not None else None
        rows.append(
            {
                "edition_id": mint_edition(edition["edition_key"]),
                "venue_id": venue_atlas_id[venue_config_id],
                "year": int(edition["year"]),
                "label": edition["label"],
                "dblp_toc_key": edition["edition_key"],
                "location": None,
                "proceedings_doi": edition.get("proceedings_doi"),
                "submissions": submissions,
                "accepted": accepted,
                "acceptance_rate": rate,
                "acceptance_source_url": source_url,
                "acceptance_source_note": source_note,
            }
        )
    rows.sort(key=lambda r: r["edition_id"])
    return rows


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
