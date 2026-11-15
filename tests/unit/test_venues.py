from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from flatatlas.cli import app
from flatatlas.venues import (
    CONFIG_DIR,
    VenueConfigError,
    load_venue_facts,
    load_venues,
    parse_venue_facts,
    parse_venues,
    profile_problems,
)


def entry(venue_id: str, **fields) -> dict:
    base = {"id": venue_id, "acronym": venue_id.upper(), "name": venue_id, "kind": "conference"}
    return {"tier": "core", **base, **fields}


def problems_of(raw: object) -> list[str]:
    with pytest.raises(VenueConfigError) as info:
        parse_venues(raw)
    return info.value.problems


# -- validation ---------------------------------------------------------------------------------


def test_valid_registry_with_predecessor_chain() -> None:
    registry = parse_venues(
        [entry("a", successor_of=["b"]), entry("b", successor_of=["c"]), entry("c")]
    )
    assert registry.ids() == ["a", "b", "c"]
    assert registry.predecessors("a") == ["b", "c"]
    assert registry.predecessors("c") == []


def test_duplicate_id_is_reported() -> None:
    assert any("duplicate venue id 'a'" in p for p in problems_of([entry("a"), entry("a")]))


def test_unknown_successor_is_reported() -> None:
    problems = problems_of([entry("a", successor_of=["ghost"])])
    assert any("unknown venue 'ghost'" in p for p in problems)


def test_successor_cycle_is_reported() -> None:
    problems = problems_of(
        [
            entry("a", successor_of=["b"]),
            entry("b", successor_of=["c"]),
            entry("c", successor_of=["a"]),
        ]
    )
    assert any(p.startswith("successor_of cycle: ") and "a" in p for p in problems)
    assert sum("cycle" in p for p in problems) == 1


def test_self_successor_is_reported_once() -> None:
    problems = problems_of([entry("a", successor_of=["a"])])
    assert problems == ["a: successor_of names itself"]


def test_bad_tier_and_kind_are_reported_with_the_venue_id() -> None:
    problems = problems_of([entry("a", tier="gold"), entry("b", kind="festival")])
    assert any(p.startswith("a: tier") for p in problems)
    assert any(p.startswith("b: kind") for p in problems)


def test_unknown_field_is_rejected() -> None:
    assert any("colour" in p for p in problems_of([entry("a", colour="red")]))


def test_malformed_ids_are_rejected() -> None:
    problems = problems_of(
        [entry("a", openalex_source_ids=["4306418189"], issn=["1234-56789"]), entry("Bad Id")]
    )
    assert any("openalex_source_ids" in p for p in problems)
    assert any("issn" in p for p in problems)
    assert any(p.startswith("Bad Id") for p in problems)


def test_year_order_and_top_level_shape() -> None:
    assert any("last_year" in p for p in problems_of([entry("a", first_year=2000, last_year=1999)]))
    assert problems_of({"id": "a"}) == ["venues.yaml: expected a list of venue entries"]


def test_all_problems_are_collected_at_once() -> None:
    problems = problems_of(
        [
            entry("a", tier="x"),
            entry("b", kind="festival"),
            entry("c", successor_of=["ghost"]),
            entry("c"),
        ]
    )
    assert len(problems) == 4  # two bad fields, one unknown successor, one duplicate id


def test_verified_date_needs_the_identifier_it_verifies() -> None:
    problems = problems_of([entry("a", verified={"dblp": "2026-11-15"})])
    assert any("dblp_stream is empty" in p for p in problems)


def test_unverified_lists_missing_sources() -> None:
    registry = parse_venues(
        [
            entry(
                "a",
                dblp_stream="conf/a",
                openalex_source_ids=["S1"],
                verified={"dblp": "2026-11-15", "openalex": "2026-11-15"},
            ),
            entry(
                "b",
                dblp_stream="conf/b",
                openalex_source_ids=["S2"],
                verified={"openalex": "2026-11-15"},
            ),
        ]
    )
    assert registry.unverified() == [("b", ["dblp"])]


# -- the real config ---------------------------------------------------------------------------


def test_shipped_registry_is_valid_and_has_the_pilot_venues() -> None:
    registry = load_venues()
    assert {"dlt", "ciaa", "dcfs"} <= set(registry.ids())
    assert registry.get("ciaa").successor_of == ["wia"]
    assert registry.get("dcfs").successor_of == ["dcagrs"]
    assert profile_problems(registry) == []
    load_venue_facts(registry=registry)


def test_profile_naming_an_unknown_venue_is_reported(tmp_path: Path) -> None:
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "x.yaml").write_text(
        yaml.safe_dump({"active_venues": ["dlt", "ghost"]})
    )
    (tmp_path / "profiles" / "y.yaml").write_text(yaml.safe_dump({"active_venues": "all"}))
    registry = parse_venues([entry("dlt")])
    assert profile_problems(registry, tmp_path) == [
        "profiles/x.yaml: active_venues names unknown venue 'ghost'"
    ]


# -- venue facts -------------------------------------------------------------------------------


def test_empty_facts_file_is_valid() -> None:
    assert parse_venue_facts({"venues": {}}).venues == {}
    assert parse_venue_facts(None).venues == {}


def test_fact_value_needs_a_source() -> None:
    registry = parse_venues([entry("a")])
    ok = {"venues": {"a": {2019: {"accepted": {"value": 22, "source_url": "https://x.org/p"}}}}}
    assert parse_venue_facts(ok, registry).venues["a"][2019].accepted.value == 22
    bad = {"venues": {"a": {2019: {"accepted": {"value": 22}}}}}
    with pytest.raises(VenueConfigError, match="needs a source_url"):
        parse_venue_facts(bad, registry)


def test_facts_for_an_unknown_venue_are_rejected() -> None:
    registry = parse_venues([entry("a")])
    with pytest.raises(VenueConfigError, match="unknown venue 'ghost'"):
        parse_venue_facts({"venues": {"ghost": {}}}, registry)


# -- CLI ---------------------------------------------------------------------------------------


def test_cli_check_passes_on_the_shipped_config() -> None:
    result = CliRunner().invoke(app, ["venues", "check"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("OK: ")


def test_cli_show_prints_entry_and_predecessors() -> None:
    result = CliRunner().invoke(app, ["venues", "show", "dcfs"])
    assert result.exit_code == 0, result.output
    assert "dblp_stream: conf/dcfs" in result.output
    assert "predecessors: dcagrs" in result.output


def test_cli_show_unknown_venue_fails_and_lists_known_ones() -> None:
    result = CliRunner().invoke(app, ["venues", "show", "nope"])
    assert result.exit_code == 1
    assert "dlt" in result.output


def test_config_dir_is_the_repo_config() -> None:
    assert (CONFIG_DIR / "venues.yaml").exists()
