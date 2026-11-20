"""The release build: manifest, checksums, forbidden columns, one tagging method (P1-09)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from flatatlas.db import connect
from flatatlas.quality import CheckResult
from flatatlas.release import build as release_build
from flatatlas.release import checks
from flatatlas.release.checks import ReleaseError
from flatatlas.settings import Settings
from flatatlas.tagging.config import load_config

TODAY = datetime(2026, 11, 20, tzinfo=UTC)
PROV = (
    "STRUCT(method VARCHAR, signals STRUCT(name VARCHAR, score FLOAT)[], "
    "models STRUCT(name VARCHAR, sha256 VARCHAR)[], tagger_version VARCHAR, "
    "taxonomy_version INTEGER, flags VARCHAR[])"
)


def _prov(method="fusion", signals=("lex_title",), version="tagger-3", flags=()):
    sigs = ", ".join(f"{{'name': '{s}', 'score': 0.5}}" for s in signals)
    fl = ", ".join(f"'{f}'" for f in flags)
    return (
        f"{{'method': '{method}', 'signals': [{sigs}]::STRUCT(name VARCHAR, score FLOAT)[], "
        f"'models': []::STRUCT(name VARCHAR, sha256 VARCHAR)[], 'tagger_version': '{version}', "
        f"'taxonomy_version': 1, 'flags': [{fl}]::VARCHAR[]}}::{PROV}"
    )


@pytest.fixture
def warehouse(settings: Settings):
    con = connect(settings.paths)
    for name, cols in {
        "core_work": "work_id VARCHAR, title VARCHAR, year SMALLINT, has_abstract BOOLEAN",
        "core_version": "version_id VARCHAR, work_id VARCHAR",
        "core_author": "author_id VARCHAR, display_name VARCHAR",
        "core_authorship": "version_id VARCHAR, author_id VARCHAR, position SMALLINT",
        "core_institution": "institution_id VARCHAR, name VARCHAR",
        "core_venue": "venue_id VARCHAR, acronym VARCHAR",
        "core_edition": "edition_id VARCHAR, venue_id VARCHAR",
        "core_citation": "citing_work_id VARCHAR, cited_work_id VARCHAR",
        "core_topic": "topic_id VARCHAR, name VARCHAR",
        "core_topic_edge": "src_topic VARCHAR, dst_topic VARCHAR, edge_type VARCHAR",
        "core_id_registry": "atlas_id VARCHAR, kind VARCHAR",
        "agg_topic_year": "topic_id VARCHAR, year SMALLINT",
        "agg_topic_author": "topic_id VARCHAR, author_id VARCHAR",
        "agg_topic_venue": "topic_id VARCHAR, venue_id VARCHAR",
        "agg_topic_work": "topic_id VARCHAR, work_id VARCHAR, rank INTEGER",
        "agg_map_layout": "topic_id VARCHAR, x FLOAT",
        "tag_work_topic": (
            "work_id VARCHAR, topic_id VARCHAR, confidence FLOAT, rank SMALLINT, "
            f"is_primary BOOLEAN, provenance {PROV}, derived BOOLEAN"
        ),
    }.items():
        con.execute(f"CREATE TABLE {name} ({cols})")
    con.execute(
        "INSERT INTO core_work VALUES "
        "('W1','a',2000,true),('W2','b',2001,false),('W3','c',2002,false)"
    )
    con.execute("INSERT INTO core_topic VALUES ('t','T')")
    rows = [
        ("W1", 0.9, _prov()),  # tagged
        ("W2", 0.3, _prov(flags=("low_confidence",))),  # low confidence; W3 is untagged
        ("W1", 0.8, _prov(method="noisy_or")),  # the other method: must not be released
    ]
    for work, conf, prov in rows:
        con.execute(f"INSERT INTO tag_work_topic VALUES ('{work}','t',{conf},1,true,{prov},false)")
    yield con
    con.close()


@pytest.fixture(autouse=True)
def passing_checks(monkeypatch):
    ok = [CheckResult("anchors[fusion]", 0.95, 0.9, True)]
    monkeypatch.setattr(checks, "data_quality", lambda con: ok)
    monkeypatch.setattr(checks, "tagger_checks", lambda reports, cfg: [])


def _build(warehouse, settings):
    return release_build.build(
        warehouse,
        settings.paths,
        load_config(),
        aggregate_version="agg-1",
        taxonomy_version=1,
        today=TODAY,
    )


def test_a_release_has_a_manifest_that_verifies(warehouse, settings):
    result = _build(warehouse, settings)
    assert result.version == "v2026.11.0"
    assert release_build.verify(result.path) == []
    files = result.manifest["files"]
    assert files["works.parquet"]["rows"] == 3
    assert {"SOURCES.md", "LICENSE.md", "CITATION.cff", "work_topics.parquet"} <= set(files)
    assert result.manifest["works_by_tag_status"] == {
        "low_confidence": 1,
        "tagged": 1,
        "untagged": 1,
    }
    assert result.manifest["tagger_version"] == "tagger-3"
    assert "CC BY 4.0" in (result.path / "LICENSE.md").read_text()
    assert 'version: "v2026.11.0"' in (result.path / "CITATION.cff").read_text()


def test_only_the_shipped_method_is_released(warehouse, settings):
    result = _build(warehouse, settings)
    n = warehouse.execute(
        "SELECT count(*), count(DISTINCT provenance.method) FROM read_parquet(?)",
        [str(result.path / "work_topics.parquet")],
    ).fetchone()
    assert n == (2, 1)  # the noisy_or row is not there


def test_the_next_release_gets_the_next_patch(warehouse, settings):
    first = _build(warehouse, settings)
    second = _build(warehouse, settings)
    assert (first.version, second.version) == ("v2026.11.0", "v2026.11.1")


def test_a_changed_file_fails_verification(warehouse, settings):
    result = _build(warehouse, settings)
    with (result.path / "works.parquet").open("ab") as fh:
        fh.write(b"x")
    problems = release_build.verify(result.path)
    assert any("works.parquet" in p for p in problems)
    (result.path / "venues.parquet").unlink()
    assert any("venues.parquet is missing" in p for p in release_build.verify(result.path))


def test_a_failed_check_writes_nothing(warehouse, settings, monkeypatch):
    bad = [CheckResult("coverage[fusion]", 0.5, 0.85, False, "adopted variant")]
    monkeypatch.setattr(checks, "data_quality", lambda con: bad)
    with pytest.raises(ReleaseError, match="coverage"):
        _build(warehouse, settings)
    assert not list(settings.paths.releases.glob("v*"))


def test_forbidden_columns_stop_the_release(warehouse, settings):
    warehouse.execute("ALTER TABLE core_work ADD COLUMN abstract VARCHAR")
    with pytest.raises(ReleaseError, match="abstract"):
        _build(warehouse, settings)
    assert not list(settings.paths.releases.glob("v*"))
    assert not list(settings.paths.releases.glob(".v*"))  # no half-written folder either


def test_the_column_rules():
    assert checks.forbidden_columns(["has_abstract", "title", "provenance.models"]) == []
    assert checks.forbidden_columns(
        ["abstract", "x.tldr", "vector", "embedding_model", "text"]
    ) == [
        "abstract",
        "x.tldr",
        "vector",
        "embedding_model",
        "text",
    ]


def test_signals_of_steps_that_are_off_stop_the_release(warehouse, settings):
    warehouse.execute("DELETE FROM tag_work_topic")
    prov = _prov(signals=("lex_title", "dm_l0"))
    warehouse.execute(f"INSERT INTO tag_work_topic VALUES ('W1','t',0.9,1,true,{prov},false)")
    with pytest.raises(ReleaseError, match="dm_l0"):
        _build(warehouse, settings)
