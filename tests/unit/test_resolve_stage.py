"""The whole resolve stage on the synthetic corpus of ``resolve_inputs``."""

from __future__ import annotations

import copy

import pytest

from flatatlas.ids import IdRegistry
from flatatlas.resolve import report
from flatatlas.resolve.locals import build_work_locals
from flatatlas.resolve.tables import SCHEMAS, to_arrow
from flatatlas.resolve.works import ResolveError, resolve_corpus
from resolve_inputs import config, make_inputs, venue_registry


def run(inputs=None, registry=None):
    registry = registry if registry is not None else IdRegistry()
    inputs = inputs if inputs is not None else make_inputs()
    return resolve_corpus(inputs, config(), venue_registry(), registry), registry, inputs


def test_versions_become_works() -> None:
    res, _, _ = run()
    assert res.stats["papers"] == 6 and res.stats["works"] == 5 and res.stats["versions"] == 6
    work = {r["work_id"]: r for r in res.works}
    a19, a21 = res.work_of_key["conf/c/A19"], res.work_of_key["journals/j/A21"]
    assert a19 == a21, "conference and journal version are one work"
    row = work[a19]
    assert row["year"] == 2019, "the work's year is the earliest version's"
    assert row["primary_version_id"] == res.version_of_key["journals/j/A21"]
    assert row["work_type"] == "article" and row["provenance"]["n_versions"] == 2
    assert (row["scope_status"], row["scope_score"]) == ("core", 1.0)
    assert res.work_of_key["conf/c/B19"] != a19, "same title, other authors: another work"
    assert len({res.work_of_key[k] for k in ("conf/c/P19a", "conf/c/P19b")}) == 2
    assert any(p.verdict == "vetoed" for p in res.pairs)


def test_version_rows_follow_the_precedence_rules() -> None:
    res, _, _ = run()
    v = {r["dblp_key"]: r for r in res.versions}
    a19 = v["conf/c/A19"]
    assert a19["pages"] == "11-22" and a19["page_count"] == 12, "Crossref wins on pages"
    assert a19["crossref_type"] == "book-chapter" and a19["volume"] == "100"
    assert a19["openalex_id"] == "W1" and a19["url_oa"] == "https://oa.example/1"
    assert v["conf/c/B19"]["pages"] == "1-10" and v["conf/c/B19"]["openalex_id"] is None
    assert (a19["merge_method"], a19["merge_confidence"]) == ("anchor", 1.0)
    a21 = v["journals/j/A21"]
    assert a21["merge_method"] == "scored-pair" and a21["merge_confidence"] >= 0.85
    assert a21["volume"] == "21" and a21["issue"] == "2"


def test_authors_are_dblp_pids_and_homonyms_stay_apart() -> None:
    res, _, _ = run()
    authors = {r["dblp_pid"]: r for r in res.authors}
    assert set(authors) == {"1/1", "2/2", "3/3", "4/4", "5/5"}
    assert authors["1/1"]["display_name"] == authors["5/5"]["display_name"] == "Ann Lee"
    assert authors["1/1"]["author_id"] != authors["5/5"]["author_id"]
    assert authors["1/1"]["openalex_ids"] == ["A100"], "two papers agree"
    assert authors["2/2"]["openalex_ids"] == ["A200"]
    assert authors["5/5"]["openalex_ids"] == []


def test_authorships_carry_affiliations_from_openalex() -> None:
    res, _, _ = run()
    v = res.version_of_key
    rows = {(r["version_id"], r["position"]): r for r in res.authorships}
    ann = rows[(v["conf/c/A19"], 1)]
    assert (ann["institution_id"], ann["country_code"]) == ("ror:01abc", "PT")
    assert ann["source"] == "dblp+openalex" and ann["raw_name"] == "Ann Lee 0001"
    assert rows[(v["conf/c/A19"], 2)]["institution_id"] == "openalex:I2"
    assert rows[(v["journals/j/A21"], 1)]["source"] == "dblp"
    assert {r["institution_id"] for r in res.institutions} == {"ror:01abc", "openalex:I2"}


def test_citations_between_versions_of_one_work_are_not_edges() -> None:
    res, _, _ = run()
    assert res.stats["citation_self_citations_dropped"] == 1
    assert all(e["citing_work_id"] != e["cited_work_id"] for e in res.citations)


def test_citations_between_works_come_from_each_source() -> None:
    res, _, _ = run()
    [edge] = res.citations
    assert edge["citing_work_id"] == res.work_of_key["conf/c/B19"]
    assert edge["cited_work_id"] == res.work_of_key["conf/c/A19"]
    assert edge["sources"] == ["s2"] and edge["is_influential"] is None
    cited = next(w for w in res.works if w["work_id"] == edge["cited_work_id"])
    assert cited["cited_by_in_corpus"] == 1
    assert cited["cited_by_count"] == 11, "the largest count over sources and versions"


def test_running_twice_gives_identical_tables_and_no_new_ids() -> None:
    first, registry, inputs = run()
    size = len(registry)
    second, _, _ = run(inputs, registry)
    assert len(registry) == size
    for name, rows_a, rows_b in (
        ("works", first.works, second.works),
        ("versions", first.versions, second.versions),
        ("authors", first.authors, second.authors),
        ("authorships", first.authorships, second.authorships),
        ("matches", first.matches, second.matches),
    ):
        assert rows_a == rows_b, name


def test_ids_survive_a_reload_of_the_registry(tmp_path) -> None:
    from flatatlas.settings import Paths

    first, registry, inputs = run()
    paths = Paths(tmp_path)
    registry.save(paths)
    second, _, _ = run(inputs, IdRegistry.load(paths))
    assert [r["work_id"] for r in first.works] == [r["work_id"] for r in second.works]


def test_a_merge_the_rules_no_longer_make_is_refused() -> None:
    _, registry, inputs = run()
    changed = copy.deepcopy(inputs)
    for p in changed.papers:
        if p["dblp_key"] == "journals/j/A21":
            p["title"] = "A Completely Different Title About Something Else"
    with pytest.raises(ResolveError, match="registry"):
        run(changed, registry)


def test_unknown_venue_and_missing_author_record_are_errors() -> None:
    bad = make_inputs()
    bad.editions[0]["venue_id"] = "nope"
    with pytest.raises(ResolveError, match="venues.yaml"):
        run(bad)
    bad = make_inputs()
    bad.authors = bad.authors[:1]
    with pytest.raises(ResolveError, match="author record"):
        run(bad)


def test_oversized_titles_in_a_rejected_openalex_record_attach_nothing() -> None:
    inputs = make_inputs()
    inputs.oa_lookup[0]["lookup_kind"] = "title"  # no DOI proof: the fuzzy rule applies
    inputs.oa_works[0]["publication_year"] = 2030
    res, _, _ = run(inputs)
    assert not any(m["source"] == "openalex" and m["external_id"] == "W1" for m in res.matches)
    assert res.rejected_matches and "year differs" in res.rejected_matches[0]["reason"]


def test_work_keyed_local_tables_have_one_row_per_work() -> None:
    res, _, inputs = run()
    abstracts, embeddings = build_work_locals(inputs, res)
    assert len(embeddings) == res.stats["works"]
    assert len({r["work_id"] for r in embeddings}) == len(embeddings)
    merged = next(r for r in embeddings if r["work_id"] == res.work_of_key["conf/c/A19"])
    assert merged["dblp_key"] == "journals/j/A21", "the primary version's vector wins"
    assert [r["work_id"] for r in abstracts] == [res.work_of_key["conf/c/A19"]]
    work = {r["work_id"]: r for r in res.works}
    assert work[res.work_of_key["conf/c/A19"]]["has_abstract"] is True


def test_every_table_converts_to_arrow_with_its_schema() -> None:
    from flatatlas.resolve.stage import table_rows

    res, _, inputs = run()
    abstracts, embeddings = build_work_locals(inputs, res)
    rows = table_rows(res) | {"local_work_abstract": abstracts, "local_work_embedding": embeddings}
    assert set(rows) == set(SCHEMAS)
    for name, data in rows.items():
        assert to_arrow(name, data).schema == SCHEMAS[name], name


def test_report_renders_the_decisions() -> None:
    res, _, inputs = run()
    text = report.render(res, inputs, profile="test")
    assert "# Resolve report — test" in text
    assert "Fast Regular Expression Matching" in text and "vetoed" in text.lower()
    assert "## 30 random cross-source joins" in text


def test_stage_reads_staging_tables_and_writes_the_core_tables(tmp_path) -> None:
    from flatatlas import quality
    from flatatlas.db import connect
    from flatatlas.resolve import stage
    from flatatlas.resolve.inputs import MissingInputs
    from flatatlas.settings import Paths
    from resolve_inputs import write_staging

    paths = Paths(tmp_path)
    con = connect(paths)
    with pytest.raises(MissingInputs, match="parse dblp"):
        stage.run(con, paths, config=config(), venue_registry=venue_registry())
    write_staging(con, make_inputs())
    result = stage.run(con, paths, config=config(), venue_registry=venue_registry())
    assert result.resolved.stats["works"] == 5 and result.resolved.stats["ids_minted"] > 0
    counts = {
        t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in ("core_work", "core_version", "core_author", "local_work_embedding")
    }
    assert counts == {
        "core_work": 5, "core_version": 6, "core_author": 5, "local_work_embedding": 5,
    }  # fmt: skip
    assert (tmp_path / "warehouse" / "core" / "core_work.parquet").exists()
    assert (tmp_path / "warehouse" / "core_id_registry.parquet").exists()
    again = stage.run(con, paths, config=config(), venue_registry=venue_registry())
    assert again.resolved.stats["ids_minted"] == 0, "a second run mints nothing"
    assert again.resolved.works == result.resolved.works
    structural = {r.check for r in quality.run_checks(con, config().quality) if not r.passed}
    assert structural <= {
        "share_matched_openalex",
        "share_matched_s2",
        "share_matched_crossref_of_doi",
    }
    con.close()


def test_cli_evaluate_data_fails_loudly(tmp_path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from flatatlas.cli import app
    from flatatlas.db import connect
    from flatatlas.resolve import stage
    from flatatlas.settings import Paths
    from resolve_inputs import write_staging

    monkeypatch.setenv("FLATATLAS_DATA_ROOT", str(tmp_path))
    runner = CliRunner()
    missing = runner.invoke(app, ["evaluate", "--data"])
    assert missing.exit_code == 1 and "flatatlas resolve" in missing.output
    paths = Paths(tmp_path)
    con = connect(paths)
    write_staging(con, make_inputs())
    stage.run(con, paths, config=config(), venue_registry=venue_registry())
    con.close()
    result = runner.invoke(app, ["evaluate", "--data"])
    assert result.exit_code == 1, "the synthetic corpus misses the real source-share thresholds"
    assert (
        "FAIL share_matched_openalex" in result.output
        and "ok   no_orphan_authorships" in result.output
    )
    con = connect(paths)
    stored = con.execute("SELECT count(*) FROM ops_quality_report").fetchone()[0]
    assert stored >= 15
    con.close()
