"""The aggregate stage end to end on a toy warehouse (P1-09, D-102)."""

from __future__ import annotations

import pytest
from export_helpers import PROV, prov
from tagging_helpers import topics_file

from flatatlas.aggregate import stage
from flatatlas.aggregate.config import load_config
from flatatlas.db import connect
from flatatlas.settings import Settings
from flatatlas.tagging.config import load_config as load_tagger_config
from flatatlas.taxonomy.stage import MissingInput

DFA = "deterministic-finite-automata"
AVOID = "avoidability"
REG = "regular-languages"


@pytest.fixture
def con(settings: Settings, monkeypatch):
    monkeypatch.setattr(stage, "load_topics", lambda path: topics_file())
    con = connect(settings.paths)
    for name, cols in {
        "core_work": (
            "work_id VARCHAR, year SMALLINT, cited_by_count INTEGER, primary_version_id VARCHAR"
        ),
        "core_version": "version_id VARCHAR, work_id VARCHAR, venue_id VARCHAR",
        "core_authorship": "version_id VARCHAR, author_id VARCHAR, position SMALLINT",
        "core_citation": "citing_work_id VARCHAR, cited_work_id VARCHAR",
        "core_venue": "venue_id VARCHAR",
        "tag_work_topic": (
            "work_id VARCHAR, topic_id VARCHAR, confidence FLOAT, rank SMALLINT, "
            f"is_primary BOOLEAN, provenance {PROV}, derived BOOLEAN"
        ),
    }.items():
        con.execute(f"CREATE TABLE {name} ({cols})")
    con.execute(
        "INSERT INTO core_work VALUES ('W1',2000,4,'P1'),('W2',2001,0,'P2'),"
        "('W3',2002,9,'P3'),('W4',2003,1,'P4')"
    )
    con.execute("INSERT INTO core_version VALUES ('P1','W1','V'),('P2','W2','V'),('P3','W3','V')")
    con.execute("INSERT INTO core_version VALUES ('P4','W4','V')")
    con.execute("INSERT INTO core_venue VALUES ('V')")
    con.execute("INSERT INTO core_authorship VALUES ('P1','A1',1),('P2','A1',1),('P3','A2',1)")
    con.execute("INSERT INTO core_citation VALUES ('W2','W1')")
    for work, topic, conf, derived, p in [
        ("W1", DFA, 0.9, False, prov()),
        ("W1", REG, 0.9, True, prov()),
        ("W2", AVOID, 0.8, False, prov()),
        ("W3", REG, 0.3, False, prov(flags=("low_confidence",))),
        ("W1", DFA, 0.5, False, prov(method="noisy_or")),  # ignored
    ]:
        con.execute(
            f"INSERT INTO tag_work_topic VALUES (?, ?, ?, 1, true, {p}, ?)",
            [work, topic, conf, derived],
        )
    yield con
    con.close()


def test_the_stage_classifies_works_and_writes_every_table(con, settings):
    result = stage.run(con, settings.paths, load_config(), load_tagger_config())
    c = result.counts
    assert (c["works"], c["tagged"], c["low_confidence"], c["untagged"]) == (4, 2, 1, 1)
    # the backbone only: the toy is far below every support floor
    assert (c["edges_related"], c["edges_builds-on"], c["edges_shared-community"]) == (0, 0, 0)
    edges = con.execute("SELECT edge_type, count(*) FROM core_topic_edge GROUP BY 1").fetchall()
    assert edges == [("subtopic-of", 2)]
    assert con.execute("SELECT count(*) FROM agg_map_layout").fetchone() == (4,)
    # roll-up: the dfa tag of W1 reaches its parent; W3's weak tag sits on regular-languages
    works = dict(
        con.execute(
            "SELECT work_id, confidence FROM agg_topic_work WHERE topic_id = ?", [REG]
        ).fetchall()
    )
    assert works["W1"] == pytest.approx(0.9) and works["W3"] == pytest.approx(0.3)
    low = dict(
        con.execute(
            "SELECT work_id, low_confidence FROM agg_topic_work WHERE topic_id = ?", [REG]
        ).fetchall()
    )
    assert low == {"W1": False, "W3": True}
    year = con.execute(
        "SELECT papers, n_low_confidence FROM agg_topic_year WHERE topic_id = ? AND year = 2002",
        [REG],
    ).fetchone()
    assert year == (0, 1)  # the weak work is counted apart, not as a paper
    assert "W4" not in {r[0] for r in con.execute("SELECT work_id FROM agg_topic_work").fetchall()}
    # a second run gives the same tables
    again = stage.run(con, settings.paths, load_config(), load_tagger_config())
    assert again.counts == result.counts


def test_the_stage_refuses_tags_of_another_tagger_version(con, settings):
    old = prov().replace("tagger-3", "tagger-2")
    con.execute("DELETE FROM tag_work_topic")
    con.execute(f"INSERT INTO tag_work_topic VALUES ('W1', '{DFA}', 0.9, 1, true, {old}, false)")
    with pytest.raises(MissingInput, match="tagger-2"):
        stage.run(con, settings.paths, load_config(), load_tagger_config())
