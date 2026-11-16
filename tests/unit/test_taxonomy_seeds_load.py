"""Seeds (CCS, MSC, OpenAlex topics), the table loader and the ``taxonomy`` commands (P1-05)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pyarrow as pa
import pytest
import yaml
from typer.testing import CliRunner

from flatatlas.cli import app
from flatatlas.db import connect
from flatatlas.taxonomy import check as tcheck
from flatatlas.taxonomy import load as tload
from flatatlas.taxonomy import seeds as tseeds
from flatatlas.taxonomy.config import SeedsConfig, config_hash, load_config

FIXTURES = Path(__file__).parent.parent / "fixtures" / "taxonomy"
runner = CliRunner()


# -- CCS -----------------------------------------------------------------------------------------


def test_ccs_parse_reads_ids_english_labels_and_both_directions_of_the_tree():
    nodes = tseeds.parse_ccs_skos((FIXTURES / "ccs_sample.xml").read_text(encoding="utf-8"))
    by_id = {n["id"]: n for n in nodes}
    assert by_id["10000001.10000002.10000004"]["label"] == "Tree languages"  # not the German one
    # the parent comes from "broader" on one concept and from "narrower" on the other
    assert by_id["10000001.10000002"]["parents"] == ["10000001"]
    assert by_id["10000001.10000009"]["parents"] == ["10000001"]
    assert by_id["20000000"]["parents"] == []
    assert len(nodes) == 7


def test_ccs_subtree_selection_keeps_descendants_and_named_single_concepts():
    nodes = tseeds.parse_ccs_skos((FIXTURES / "ccs_sample.xml").read_text(encoding="utf-8"))
    kept = tseeds.select_ccs_subtree(
        nodes, ["Formal languages and automata theory"], ["Models of computation"]
    )
    labels = {n["label"] for n in kept}
    assert labels == {
        "Formal languages and automata theory",
        "Regular languages",
        "Tree languages",
        "Models of computation",
    }  # not the root, not the quantum child of "Models of computation", not software
    by_label = {n["label"]: n for n in kept}
    assert by_label["Regular languages"]["parents"] == ["10000001.10000002"]
    assert by_label["Formal languages and automata theory"]["parents"] == []  # root is outside


def test_ccs_selection_rejects_a_file_without_the_expected_labels():
    nodes = tseeds.parse_ccs_skos((FIXTURES / "ccs_sample.xml").read_text(encoding="utf-8"))
    with pytest.raises(tseeds.SeedError, match="Nonexistent"):
        tseeds.select_ccs_subtree(nodes, ["Nonexistent"], [])
    with pytest.raises(tseeds.SeedError, match="not valid XML"):
        tseeds.parse_ccs_skos("<rdf:RDF")


def test_ccs_yaml_states_source_and_terms_and_is_a_valid_xref_source(tmp_path):
    counts = tseeds.build_seeds(
        None,
        SeedsConfig(ccs_subtrees=["Formal languages and automata theory"]),
        ccs_file=FIXTURES / "ccs_sample.xml",
        out_dir=tmp_path,
    )
    assert counts == {"ccs_concepts_in_file": 7, "ccs_concepts_kept": 3}
    data = yaml.safe_load((tmp_path / "ccs.yaml").read_text(encoding="utf-8"))
    assert "copyright" in data["source"] and "educational and research" in data["source"]
    from flatatlas.taxonomy.schema import Xref

    Xref(ccs=[n["id"] for n in data["concepts"]])  # the ids pass the xref format check


def test_msc_seed_has_our_own_wording_and_valid_codes():
    from flatatlas.taxonomy.schema import MSC_CODE

    codes = tseeds.load_msc()
    assert {c["code"] for c in codes} >= {"68Q45", "68Q70", "68Q42", "68R15", "68Q80", "03D05"}
    assert all(MSC_CODE.match(c["code"]) and c["ours"] for c in codes)
    assert {c["guarded"] for c in codes} == {True, False}


# -- OpenAlex seed -------------------------------------------------------------------------------


def test_openalex_seed_counts_topics_and_keeps_keywords_untrusted():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE stg_openalex_topic (openalex_id VARCHAR, kind VARCHAR, rank SMALLINT, "
        "topic_id VARCHAR, name VARCHAR, score FLOAT, subfield VARCHAR, field VARCHAR, "
        "domain VARCHAR)"
    )
    rows = [
        ("W1", "topic", 1, "T1", "automata", 0.9, "sf", "f", "d"),
        ("W2", "topic", 1, "T1", "automata", 0.7, "sf", "f", "d"),
        ("W3", "topic", 1, "T2", "once", 0.5, "sf", "f", "d"),
        ("W1", "keyword", 1, None, "regular language", 0.5, None, None, None),
        ("W2", "keyword", 1, None, "regular language", 0.5, None, None, None),
        ("W3", "keyword", 1, None, "rare", 0.5, None, None, None),
    ]
    con.executemany("INSERT INTO stg_openalex_topic VALUES (?,?,?,?,?,?,?,?,?)", rows)
    seed = tseeds.openalex_seed(con, min_works=2)
    assert [t["id"] for t in seed["topics"]] == ["T1"]
    assert seed["topics"][0]["n_works"] == 2 and seed["topics"][0]["mean_score"] == 0.8
    assert seed["keywords"]["trusted"] is False
    assert seed["keywords"]["items"] == [{"name": "regular language", "n_works": 2}]


# -- loader --------------------------------------------------------------------------------------


def test_topic_and_edge_rows_follow_plan_4_3():
    topics = tcheck.parse_topics((FIXTURES / "topics_valid.yaml").read_text(encoding="utf-8"))
    rows, edges = tload.topic_rows(topics)
    by_id = {r["topic_id"]: r for r in rows}
    assert by_id["unary-languages"]["level"] == 2 and by_id["regular-languages"]["level"] == 0
    assert by_id["regular-languages"]["xref_msc"] == ["68Q45"]
    assert by_id["descriptional-complexity"]["include_phrases"] == ["state complexity", "size"]
    shuffle_edges = [e for e in edges if e["src_topic"] == "shuffle-of-words"]
    assert {e["dst_topic"] for e in shuffle_edges} == {
        "regular-languages",
        "context-free-languages",
    }
    assert all(e["edge_type"] == "subtopic-of" for e in edges)
    assert all(e["provenance"]["method"] == "topics.yaml" for e in edges)
    # reviewed topics carry confidence 1; proposals leave it empty (rule 4: never invented)
    unreviewed = next(e for e in edges if e["src_topic"] == "unary-languages")
    assert unreviewed["confidence"] is None


def test_gold_rows_are_one_per_label_and_loadable(tmp_path, settings):
    gold = tcheck.parse_gold((FIXTURES / "gold_valid.yaml").read_text(encoding="utf-8"))
    topics = tcheck.parse_topics((FIXTURES / "topics_valid.yaml").read_text(encoding="utf-8"))
    con = connect(settings.paths)
    try:
        counts = tload.write_gold(con, settings.paths, gold)
        tload.write_topics(con, settings.paths, topics)
        n = con.execute("SELECT count(*) FROM eval_gold").fetchone()[0]
        assert n == counts["labels"] == sum(len(w.labels) for w in gold.works)
        assert con.execute("SELECT count(*) FROM core_topic").fetchone()[0] == 5
        assert (settings.paths.warehouse / "eval" / "eval_gold.parquet").exists()
        assert con.execute("DESCRIBE eval_gold").fetchall()[0][0] == "work_id"
    finally:
        con.close()
    for schema in tload.SCHEMAS.values():
        assert isinstance(schema, pa.Schema)


# -- commands ------------------------------------------------------------------------------------


def warehouse_with_works(settings, work_ids: list[str]) -> None:
    con = connect(settings.paths)
    con.execute("CREATE TABLE core_work (work_id VARCHAR)")
    con.executemany("INSERT INTO core_work VALUES (?)", [(w,) for w in work_ids])
    con.close()


def test_check_command_accepts_the_valid_pair_and_rejects_each_broken_gold(settings, monkeypatch):
    monkeypatch.setenv("FLATATLAS_DATA_ROOT", str(settings.paths.root))
    gold = tcheck.parse_gold((FIXTURES / "gold_valid.yaml").read_text(encoding="utf-8"))
    warehouse_with_works(settings, [w.work for w in gold.works])
    topics_arg = ["--topics", str(FIXTURES / "topics_valid.yaml")]
    ok = runner.invoke(
        app, ["taxonomy", "check", *topics_arg, "--gold", str(FIXTURES / "gold_valid.yaml")]
    )
    assert ok.exit_code == 0, ok.output
    assert "OK" in ok.output
    for broken in sorted(FIXTURES.glob("gold_broken_*.yaml")):
        bad = runner.invoke(app, ["taxonomy", "check", *topics_arg, "--gold", str(broken)])
        assert bad.exit_code == 1, f"{broken.name} was accepted"
        assert "error:" in bad.output


def test_check_command_passes_trivially_when_the_files_do_not_exist(
    settings, monkeypatch, tmp_path
):
    monkeypatch.setenv("FLATATLAS_DATA_ROOT", str(settings.paths.root))
    result = runner.invoke(
        app,
        [
            "taxonomy",
            "check",
            "--topics",
            str(tmp_path / "no.yaml"),
            "--gold",
            str(tmp_path / "no2.yaml"),
        ],
    )
    assert result.exit_code == 0 and "nothing to check" in result.output


def test_load_command_writes_core_tables(settings, monkeypatch):
    monkeypatch.setenv("FLATATLAS_DATA_ROOT", str(settings.paths.root))
    result = runner.invoke(
        app,
        [
            "taxonomy",
            "load",
            "--topics",
            str(FIXTURES / "topics_valid.yaml"),
            "--gold",
            str(FIXTURES / "gold_valid.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    con = connect(settings.paths, read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM core_topic_edge").fetchone()[0] == 4
    finally:
        con.close()


def test_the_repo_taxonomy_config_loads_and_hashes_stably():
    cfg = load_config()
    assert cfg.cluster.granularities == [12, 30, 70]
    assert config_hash(cfg) == config_hash(load_config())
