"""The static export: layout of files, content, validation against the models (P1-09)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from export_helpers import build_release, make_warehouse, patch_checks
from pydantic import TypeAdapter

from flatatlas.db import connect
from flatatlas.export import models as m
from flatatlas.export import static
from flatatlas.settings import PROJECT_ROOT, Settings

FIXTURE = PROJECT_ROOT / "web" / "static" / "data-fixture"


@pytest.fixture
def exported(settings: Settings, monkeypatch, tmp_path: Path):
    patch_checks(monkeypatch)
    con = connect(settings.paths)
    make_warehouse(con)
    release = build_release(con, settings.paths)
    con.close()
    out = tmp_path / "site"
    result = static.export_static(release.path, out)
    return out, result, release


def read(out: Path, name: str):
    return json.loads((out / name).read_text("utf-8"))


def test_shard_rule_matches_the_web_code():
    # The same values as StaticDataSource.spec.ts: works/1e.json holds WFIXTUREAAA.
    assert static.shard_of("WFIXTUREAAA") == "1e"
    assert static.shard_of("AFIXTUREAAA") == "3f"


def test_topics_json(exported):
    out, *_ = exported
    topics = {t["topic_id"]: t for t in read(out, "topics.json")}
    assert topics["a"]["children"] == ["b"] and topics["b"]["parents"] == ["a"]
    assert topics["a"]["description"] == "The top topic."  # whitespace is collapsed
    assert topics["a"]["paper_count"] == 1 and topics["a"]["volume"] == pytest.approx(0.9)
    # a topic with only a weakly matched work: no paper, a low-confidence count of one
    assert topics["c"]["paper_count"] == 0 and topics["c"]["n_low_confidence"] == 1


def test_topic_page_edges_papers_and_authors(exported):
    out, *_ = exported
    page = read(out, "topic/b.json")
    assert [p["topic_id"] for p in page["parents"]] == ["a"]
    related = page["edges"]["related"]
    assert [(e["topic_id"], e["direction"]) for e in related] == [("c", "both")]
    # c builds on b: seen from b, the other topic builds on this one
    assert [(e["topic_id"], e["direction"]) for e in page["edges"]["builds-on"]] == [("c", "in")]
    assert page["edges"]["shared-community"] == []
    assert [p["work_id"] for p in page["top_papers"]] == ["W1"]
    assert page["top_papers"][0]["venue_acronym"] == "CONF"
    assert [(a["author_id"], a["score"]) for a in page["key_authors"]] == [("A1", 0.9), ("A2", 0.9)]
    assert page["year_series"] == [{"year": 2000, "papers": 1, "volume": 0.9}]
    # the other end sees the same builds-on edge as outgoing
    assert read(out, "topic/c.json")["edges"]["builds-on"][0]["direction"] == "out"
    assert read(out, "topic/c.json")["top_papers"][0]["low_confidence"] is True


def test_works_untagged_and_low_confidence_are_kept(exported):
    out, *_ = exported
    works = {}
    for path in (out / "works").glob("*.json"):
        works |= json.loads(path.read_text("utf-8"))
    assert set(works) == {"W1", "W2", "W3"}
    w1 = works["W1"]
    assert w1["tag_status"] == "tagged"
    assert [(t["topic_id"], t["derived"]) for t in w1["tags"]] == [("b", False), ("a", True)]
    assert w1["tags"][0]["provenance"]["signals"] == {"lex_title": 0.5}
    assert w1["tags"][0]["provenance"]["taxonomy_version"] == "1"
    assert w1["links"] == {
        "dblp": "https://dblp.org/rec/conf/c/One00",
        "openalex": "https://openalex.org/W11",
        "doi": "https://doi.org/10.1/x",
        "open_access": "https://oa.example/1",
    }
    assert [a["name"] for a in w1["authors"]] == ["Ada One", "Bo Two"]
    assert works["W2"]["tag_status"] == "low_confidence"
    assert works["W2"]["tags"][0]["provenance"]["flags"] == ["low_confidence"]
    assert works["W3"]["tag_status"] == "untagged" and works["W3"]["tags"] == []
    # the noisy-or row of W1 is not in the release and so not in the site data
    assert len(w1["tags"]) == 2


def test_authors_list_their_works_newest_first(exported):
    out, *_ = exported
    authors = {}
    for path in (out / "authors").glob("*.json"):
        authors |= json.loads(path.read_text("utf-8"))
    assert authors["A1"]["work_ids"] == ["W2", "W1"]
    assert [t["topic_id"] for t in authors["A1"]["topics"]] == ["a", "b", "c"]
    assert authors["A2"]["name_variants"] == ["B. Two"]


def test_map_search_and_meta(exported):
    out, result, release = exported
    nodes = {n["topic_id"]: n for n in read(out, "map.json")["nodes"]}
    assert nodes["b"]["parent_id"] == "a" and nodes["b"]["ghost_parents"] == ["c"]
    search = read(out, "search/index.json")
    assert [t["aliases"] for t in search["topics"] if t["topic_id"] == "a"] == [["alpha"]]
    assert len(search["works"]) == 3
    meta = read(out, "meta.json")
    assert meta["release"] == release.version == "v2026.11.0"
    assert meta["works_by_tag_status"] == {"low_confidence": 1, "tagged": 1, "untagged": 1}


def test_every_file_validates_against_its_model(exported):
    out, result, _ = exported
    checks = [
        ("topics.json", TypeAdapter(list[m.Topic])),
        ("map.json", TypeAdapter(m.MapLayout)),
        ("search/index.json", TypeAdapter(m.SearchIndex)),
        ("meta.json", TypeAdapter(m.DataInfo)),
    ]
    seen = 0
    for name, adapter in checks:
        adapter.validate_json((out / name).read_text("utf-8"))
        seen += 1
    for path in (out / "topic").glob("*.json"):
        m.TopicPage.model_validate_json(path.read_text("utf-8"))
        seen += 1
    for path in (out / "venue").glob("*.json"):
        m.Venue.model_validate_json(path.read_text("utf-8"))
        seen += 1
    for folder, model in (("works", m.Work), ("authors", m.Author)):
        for path in (out / folder).glob("*.json"):
            for entry in json.loads(path.read_text("utf-8")).values():
                model.model_validate(entry)
            seen += 1
    assert seen == result.files


def test_no_abstract_text_leaves_in_the_site_data(exported):
    out, *_ = exported
    for path in out.rglob("*.json"):
        assert "abstract" not in path.read_text("utf-8").lower()


def test_a_second_export_replaces_stale_files(exported):
    out, _, release = exported
    (out / "topic" / "stale.json").write_text("{}")
    static.export_static(release.path, out)
    assert not (out / "topic" / "stale.json").exists()


def test_a_tampered_release_is_refused(exported, tmp_path):
    _, _, release = exported
    with (release.path / "topics.parquet").open("ab") as fh:
        fh.write(b"x")
    with pytest.raises(static.ExportError, match="manifest"):
        static.export_static(release.path, tmp_path / "again")


def test_the_hand_written_fixtures_follow_the_same_models():
    topics = TypeAdapter(list[m.Topic]).validate_json((FIXTURE / "topics.json").read_text("utf-8"))
    assert topics
    for path in (FIXTURE / "topic").glob("*.json"):
        m.TopicPage.model_validate_json(path.read_text("utf-8"))
    for path in (FIXTURE / "works").glob("*.json"):
        for entry in json.loads(path.read_text("utf-8")).values():
            m.Work.model_validate(entry)
    for path in (FIXTURE / "authors").glob("*.json"):
        for entry in json.loads(path.read_text("utf-8")).values():
            m.Author.model_validate(entry)
    for path in (FIXTURE / "venue").glob("*.json"):
        m.Venue.model_validate_json(path.read_text("utf-8"))
    m.MapLayout.model_validate_json((FIXTURE / "map.json").read_text("utf-8"))
