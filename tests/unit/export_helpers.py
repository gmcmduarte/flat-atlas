"""A toy warehouse with the tables the release and the static export read (P1-09)."""

from __future__ import annotations

from datetime import UTC, datetime

import duckdb

from flatatlas.quality import CheckResult
from flatatlas.release import build as release_build
from flatatlas.release import checks
from flatatlas.settings import Paths
from flatatlas.tagging.config import load_config

TODAY = datetime(2026, 11, 20, tzinfo=UTC)
PROV = (
    "STRUCT(method VARCHAR, signals STRUCT(name VARCHAR, score FLOAT)[], "
    "models STRUCT(name VARCHAR, sha256 VARCHAR)[], tagger_version VARCHAR, "
    "taxonomy_version INTEGER, flags VARCHAR[])"
)
SIG = "STRUCT(name VARCHAR, score FLOAT)[]"


def prov(method="fusion", flags=()):
    fl = ", ".join(f"'{f}'" for f in flags)
    return (
        f"{{'method': '{method}', 'signals': [{{'name': 'lex_title', 'score': 0.5}}]::{SIG}, "
        f"'models': []::STRUCT(name VARCHAR, sha256 VARCHAR)[], 'tagger_version': 'tagger-3', "
        f"'taxonomy_version': 1, 'flags': [{fl}]::VARCHAR[]}}::{PROV}"
    )


TABLES = {
    "core_work": (
        "work_id VARCHAR, title VARCHAR, year SMALLINT, work_type VARCHAR, "
        "primary_version_id VARCHAR, has_abstract BOOLEAN, cited_by_count INTEGER"
    ),
    "core_version": (
        "version_id VARCHAR, work_id VARCHAR, venue_id VARCHAR, year SMALLINT, volume VARCHAR, "
        "pages VARCHAR, doi VARCHAR, dblp_key VARCHAR, openalex_id VARCHAR, url_oa VARCHAR, "
        "url_landing VARCHAR"
    ),
    "core_author": (
        "author_id VARCHAR, display_name VARCHAR, name_variants VARCHAR[], dblp_pid VARCHAR, "
        "orcid VARCHAR"
    ),
    "core_authorship": "version_id VARCHAR, author_id VARCHAR, position SMALLINT",
    "core_institution": "institution_id VARCHAR, name VARCHAR",
    "core_venue": (
        "venue_id VARCHAR, acronym VARCHAR, name VARCHAR, kind VARCHAR, tier VARCHAR, "
        "first_year SMALLINT, last_year SMALLINT, successor_of VARCHAR[], homepage VARCHAR"
    ),
    "core_edition": "edition_id VARCHAR, venue_id VARCHAR",
    "core_citation": "citing_work_id VARCHAR, cited_work_id VARCHAR",
    "core_topic": (
        "topic_id VARCHAR, name VARCHAR, aliases VARCHAR[], description VARCHAR, level SMALLINT"
    ),
    "core_topic_edge": (
        "src_topic VARCHAR, dst_topic VARCHAR, edge_type VARCHAR, weight FLOAT, confidence FLOAT"
    ),
    "core_id_registry": "atlas_id VARCHAR, kind VARCHAR",
    "agg_topic_year": (
        "topic_id VARCHAR, year SMALLINT, papers INTEGER, volume FLOAT, citations BIGINT, "
        "n_low_confidence INTEGER"
    ),
    "agg_topic_author": "topic_id VARCHAR, author_id VARCHAR, score FLOAT, n_works INTEGER",
    "agg_topic_venue": "topic_id VARCHAR, venue_id VARCHAR, papers INTEGER",
    "agg_topic_work": (
        "topic_id VARCHAR, work_id VARCHAR, confidence FLOAT, score FLOAT, rank INTEGER, "
        "low_confidence BOOLEAN"
    ),
    "agg_map_layout": (
        "topic_id VARCHAR, parent_id VARCHAR, level SMALLINT, x FLOAT, y FLOAT, r FLOAT, "
        "year SMALLINT, volume FLOAT, ghost_parents VARCHAR[]"
    ),
    "tag_work_topic": (
        "work_id VARCHAR, topic_id VARCHAR, confidence FLOAT, rank SMALLINT, "
        f"is_primary BOOLEAN, provenance {PROV}, derived BOOLEAN"
    ),
}

ROWS = {
    "core_work": [
        "('W1','First paper',2000,'proceedings-paper','P1',true,5)",
        "('W2','Second paper',2001,'proceedings-paper','P2',false,0)",
        "('W3','Third paper',2002,'proceedings-paper','P3',false,2)",
    ],
    "core_version": [
        "('P1','W1','V1',2000,'1','1-10','10.1/x','conf/c/One00','W11','https://oa.example/1',NULL)",
        "('P2','W2','V1',2001,NULL,NULL,NULL,'conf/c/Two01',NULL,NULL,NULL)",
        "('P3','W3','V1',2002,NULL,NULL,NULL,NULL,NULL,NULL,NULL)",
        "('P1b','W1','V9',2001,'2',NULL,NULL,NULL,NULL,NULL,'https://j.example/1')",
    ],
    "core_author": [
        "('A1','Ada One',[]::VARCHAR[],'1/1','0000-0000-0000-0001')",
        "('A2','Bo Two',['B. Two'],NULL,NULL)",
    ],
    "core_authorship": ["('P1','A1',1)", "('P1','A2',2)", "('P2','A1',1)"],
    "core_venue": [
        "('V1','CONF','A Conference','conference','core',1999,NULL,[]::VARCHAR[],NULL)",
        "('V9','JRNL','A Journal','journal','core',1990,NULL,[]::VARCHAR[],NULL)",
    ],
    "core_citation": ["('W2','W1')", "('W3','W1')", "('W3','W2')", "('W3','WX')"],
    "core_topic": [
        "('a','Alpha',['alpha'],'The  top\ntopic.',0)",
        "('b','Beta',[]::VARCHAR[],'A child.',1)",
        "('c','Gamma',[]::VARCHAR[],'Another root.',0)",
    ],
    "core_topic_edge": [
        "('b','a','subtopic-of',1.0,1.0)",
        "('b','c','related',0.5,0.8)",
        "('c','b','builds-on',0.3,0.9)",
    ],
    "agg_topic_year": [
        "('a',2000,1,0.9,5,0)",
        "('b',2000,1,0.9,5,0)",
        "('c',2001,0,0.3,0,1)",
    ],
    "agg_topic_author": [
        "('a','A1',0.9,1)",
        "('b','A1',0.9,1)",
        "('b','A2',0.9,1)",
        "('c','A1',0.3,0)",
    ],
    "agg_topic_venue": ["('a','V1',1)", "('b','V1',1)", "('c','V1',0)"],
    "agg_topic_work": [
        "('a','W1',0.9,1.6,1,false)",
        "('b','W1',0.9,1.6,1,false)",
        "('c','W2',0.3,0.0,1,true)",
    ],
    "agg_map_layout": [
        "('a',NULL,0,-10.0,0.0,20.0,NULL,0.9,[]::VARCHAR[])",
        "('c',NULL,0,40.0,0.0,10.0,NULL,0.3,[]::VARCHAR[])",
        "('b','a',1,-10.0,0.0,15.0,NULL,0.9,['c'])",
    ],
}


def make_warehouse(con: duckdb.DuckDBPyConnection) -> None:
    for name, cols in TABLES.items():
        con.execute(f"CREATE TABLE {name} ({cols})")
    for name, rows in ROWS.items():
        for row in rows:
            con.execute(f"INSERT INTO {name} VALUES {row}")
    for work, topic, conf, rank, primary, derived, p in [
        ("W1", "b", 0.9, 1, True, False, prov()),
        ("W1", "a", 0.9, 2, False, True, prov()),
        ("W2", "c", 0.3, 1, True, False, prov(flags=("low_confidence",))),
        ("W1", "b", 0.8, 1, True, False, prov(method="noisy_or")),  # never released
    ]:
        con.execute(
            "INSERT INTO tag_work_topic VALUES (?, ?, ?, ?, ?, " + p + ", ?)",
            [work, topic, conf, rank, primary, derived],
        )


def patch_checks(monkeypatch) -> None:
    ok = [CheckResult("anchors[fusion]", 0.95, 0.9, True)]
    monkeypatch.setattr(checks, "data_quality", lambda con: ok)
    monkeypatch.setattr(checks, "tagger_checks", lambda reports, cfg: [])


def build_release(con: duckdb.DuckDBPyConnection, paths: Paths):
    return release_build.build(
        con,
        paths,
        load_config(),
        aggregate_version="agg-1",
        taxonomy_version=1,
        today=TODAY,
    )
