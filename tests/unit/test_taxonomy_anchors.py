"""Anchor papers: the schema, the offline rules of ``taxonomy check`` and the verification of
identifiers against OpenAlex, the warehouse and the DBLP dump (P1-06)."""

from __future__ import annotations

import copy
from pathlib import Path

import duckdb
import httpx
import pytest
import yaml
from typer.testing import CliRunner

from flatatlas.cli import app
from flatatlas.http import SourceClient
from flatatlas.taxonomy import anchors as tanchors
from flatatlas.taxonomy import check as tcheck
from helpers import FakeClock

FIXTURES = Path(__file__).parent.parent / "fixtures"
TAX = FIXTURES / "taxonomy"
DUMP = FIXTURES / "dblp" / "dblp_sample.xml.gz"
DTD = FIXTURES / "dblp" / "dblp.dtd"
runner = CliRunner()


def valid() -> dict:
    return yaml.safe_load((TAX / "anchors_valid.yaml").read_text(encoding="utf-8"))


def topics():
    return tcheck.load_topics(TAX / "topics_valid.yaml")


def problems_of(data: dict, **kwargs) -> list[str]:
    return tcheck.check_anchors(tcheck.parse_anchors(yaml.safe_dump(data)), topics(), **kwargs)


# -- schema and offline rules ---------------------------------------------------------------------


def test_valid_file_passes_and_dois_are_normalised():
    file = tcheck.parse_anchors(yaml.safe_dump(valid()))
    assert tcheck.check_anchors(file, topics()) == []
    by_id = {a.id: a for a in file.anchors}
    assert by_id["jiraskova-nfa-dfa-trade-off"].doi == "10.1007/978-3-030-23247-4_14"


@pytest.mark.parametrize(
    "field, value",
    [("doi", "not-a-doi"), ("dblp", "Rabin Scott 1959"), ("id", "Rabin_Scott"), ("year", 1850),
     ("kind", "famous")],
)  # fmt: skip
def test_malformed_fields_are_rejected_by_the_schema(field, value):
    data = valid()
    data["anchors"][0][field] = value
    with pytest.raises(tcheck.TaxonomyFileError):
        tcheck.parse_anchors(yaml.safe_dump(data))


def _set(i, **fields):
    def mutate(d):
        d["anchors"][i].update(fields)

    return mutate


@pytest.mark.parametrize(
    "mutate, message",
    [
        (_set(0, topic="no-such-topic"), "is not a topic"),
        (_set(2, dblp=None), "needs a doi or a dblp key"),
        (_set(1, id="rabin-scott-1959"), "listed twice"),
        (_set(1, doi="10.1147/RD.32.0114"), "used by several anchors"),
        (lambda d: d.update(taxonomy_version=2), "taxonomy_version"),
    ],
)
def test_each_broken_rule_is_reported(mutate, message):
    data = valid()
    mutate(data)
    found = problems_of(data)
    assert any(message in p for p in found), found


def test_reviewed_anchor_cannot_change_without_the_flag():
    head = tcheck.parse_anchors(yaml.safe_dump(valid()))
    data = copy.deepcopy(valid())
    data["anchors"][0]["topic"] = "descriptional-complexity"
    assert any("reviewed anchor changed" in p for p in problems_of(data, head=head))
    assert problems_of(data, head=head, allow_reviewed_edits=True) == []
    data["anchors"] = data["anchors"][1:]
    assert any("reviewed anchor removed" in p for p in problems_of(data, head=head))


def test_expected_topics_of_venues_must_be_active_topics():
    assert tcheck.check_expected_topics({"dcfs": ["descriptional-complexity"]}, topics()) == []
    found = tcheck.check_expected_topics({"dcfs": ["state-complexity"]}, topics())
    assert found == ["venue dcfs: expected topic 'state-complexity' is not a topic"]


def test_the_repo_anchor_file_loads_when_present():
    if tcheck.ANCHORS_FILE.exists():
        tcheck.load_anchors(tcheck.ANCHORS_FILE)


# -- verification ---------------------------------------------------------------------------------


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("CREATE TABLE core_work (work_id VARCHAR, title VARCHAR)")
    c.execute(
        "CREATE TABLE core_version (work_id VARCHAR, doi VARCHAR, dblp_key VARCHAR, year SMALLINT)"
    )
    c.execute(
        "INSERT INTO core_work VALUES "
        "('WAAAAAAAAAA', 'NFA-to-DFA Trade-Off for Regular Operations')"
    )
    c.execute(
        "INSERT INTO core_version VALUES ('WAAAAAAAAAA', '10.1007/978-3-030-23247-4_14', "
        "'conf/dcfs/JiraskovaK19', 2019)"
    )
    yield c
    c.close()


def client(settings, clock: FakeClock) -> SourceClient:
    return SourceClient(
        "openalex", settings, clock=clock.monotonic, sleep=clock.sleep, now=clock.now
    )


def serve(httpx_mock, works: dict[str, dict]) -> list[str]:
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        doi = request.url.path.removeprefix("/works/doi:")
        asked.append(doi)
        assert "select=id%2Cdoi%2Ctitle%2Cpublication_year" in str(request.url)
        if doi in works:
            return httpx.Response(200, json=works[doi])
        return httpx.Response(404, json={"error": "not found"})

    httpx_mock.add_callback(answer, is_reusable=True, is_optional=True)
    return asked


RABIN_SCOTT = {
    "id": "https://openalex.org/W2",
    "doi": "https://doi.org/10.1147/rd.32.0114",
    "title": "Finite Automata and Their Decision Problems",
    "publication_year": 1959,
}
JIRASKOVA = {
    "id": "https://openalex.org/W1",
    "doi": "https://doi.org/10.1007/978-3-030-23247-4_14",
    "title": "NFA-to-DFA Trade-Off for Regular Operations",
    "publication_year": 2019,
}


def test_verify_checks_titles_years_and_corpus_membership(settings, con, httpx_mock, clock):
    serve(httpx_mock, {"10.1147/rd.32.0114": RABIN_SCOTT,
                       "10.1007/978-3-030-23247-4_14": JIRASKOVA})  # fmt: skip
    oa = client(settings, clock)
    file = tcheck.parse_anchors(yaml.safe_dump(valid()))
    corpus = tanchors.load_corpus(con)
    keys = tanchors.needs_dump(file.anchors, corpus)
    assert keys == ["conf/dlt/Roder93"]
    by_key, _ = tanchors.scan_dump(DUMP, DTD, keys=keys)
    statuses = tanchors.verify(
        file.anchors, corpus, doi_lookup=lambda d: tanchors.lookup_doi(oa, d), dump_records=by_key
    )
    by_id = {s.anchor.id: s for s in statuses}
    assert by_id["rabin-scott-1959"].ok and by_id["rabin-scott-1959"].work_id is None
    assert by_id["jiraskova-nfa-dfa-trade-off"].work_id == "WAAAAAAAAAA"
    assert len(by_id["jiraskova-nfa-dfa-trade-off"].verified) == 2  # doi and dblp
    # pilot anchor not in the (tiny) corpus: the key exists in the dump, but kind is wrong
    roder = by_id["roder-bnlc"]
    assert roder.verified and any("not in the corpus" in p for p in roder.problems)


def test_wrong_title_unknown_doi_and_offline_cache(settings, con, httpx_mock, clock):
    asked = serve(httpx_mock, {"10.1147/rd.32.0114": RABIN_SCOTT})
    oa = client(settings, clock)
    data = valid()
    data["anchors"][0]["title"] = "On Computable Numbers"
    data["anchors"][1]["doi"] = "10.9999/does-not-exist"
    data["anchors"] = data["anchors"][:2]
    file = tcheck.parse_anchors(yaml.safe_dump(data))
    corpus = tanchors.load_corpus(con)
    statuses = tanchors.verify(
        file.anchors, corpus, doi_lookup=lambda d: tanchors.lookup_doi(oa, d), dump_records={}
    )
    assert any("different title" in p for p in statuses[0].problems)
    assert any("does not know it" in p for p in statuses[1].problems)
    n = len(asked)
    again = tanchors.verify(
        file.anchors,
        corpus,
        doi_lookup=lambda d: tanchors.lookup_doi(oa, d, offline=True),
        dump_records={},
    )
    assert len(asked) == n  # offline reads the cache only, 404s included
    assert [s.problems for s in again] == [s.problems for s in statuses]


def test_unread_dump_leaves_outside_keys_unchecked(con):
    file = tcheck.parse_anchors(yaml.safe_dump(valid()))
    roder = [a for a in file.anchors if a.id == "roder-bnlc"]
    [status] = tanchors.verify(roder, tanchors.load_corpus(con), doi_lookup=lambda d: None,
                               dump_records=None)  # fmt: skip
    assert any("dump was not read" in p for p in status.problems)


def test_find_by_title_in_the_dump_returns_key_and_doi():
    anchor = (
        tcheck.parse_anchors(yaml.safe_dump(valid()))
        .anchors[1]
        .model_copy(
            update={
                "doi": None,
                "dblp": None,
                "title": "NFA-to-DFA trade-off for regular operations",
            }
        )
    )
    _, by_title = tanchors.scan_dump(DUMP, DTD, titles=[anchor.title])
    cands = tanchors.candidates(anchor, by_title[tanchors.normalize_title(anchor.title)])
    assert cands[0][1].dblp == "conf/dcfs/JiraskovaK19"
    assert cands[0][1].doi == "10.1007/978-3-030-23247-4_14"
    late = anchor.model_copy(update={"year": 2015})
    assert tanchors.candidates(late, by_title[tanchors.normalize_title(anchor.title)]) == []


def test_a_title_inside_a_prefixed_title_matches_but_a_fragment_does_not():
    full = "Programming Techniques: Regular expression search algorithm"
    assert tanchors.title_match("Regular Expression Search Algorithm", full) == 1.0
    assert tanchors.title_match("Regular Expression", full) < tanchors.TITLE_MIN


def test_a_year_difference_is_a_note_when_the_title_matches(con):
    file = tcheck.parse_anchors(yaml.safe_dump(valid()))
    rabin = [a for a in file.anchors if a.id == "rabin-scott-1959"]
    late = tanchors.Found("openalex", RABIN_SCOTT["title"], 1962, "10.1147/rd.32.0114")
    [status] = tanchors.verify(rabin, tanchors.load_corpus(con), doi_lookup=lambda d: late)
    assert status.ok and status.notes == ["doi: openalex gives year 1962, not 1959"]


def test_title_search_params_cover_the_year_slack():
    params = tanchors.title_search_params("Finite Automata: and Their (Decision) Problems", 1959)
    assert params["filter"] == (
        "title.search:Finite Automata and Their Decision Problems,publication_year:1958|1959|1960"
    )


# -- commands -------------------------------------------------------------------------------------


def test_check_command_checks_anchors_only_when_asked_for_a_draft(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("FLATATLAS_DATA_ROOT", str(settings.paths.root))
    topics_arg = ["--topics", str(TAX / "topics_valid.yaml"), "--gold", str(tmp_path / "no.yaml")]
    ok = runner.invoke(app, ["taxonomy", "check", *topics_arg])
    assert ok.exit_code == 0, ok.output
    assert "anchors" not in ok.output  # the repo's anchors are not checked against a draft
    good = runner.invoke(app, ["taxonomy", "check", *topics_arg, "--anchors",
                               str(TAX / "anchors_valid.yaml")])  # fmt: skip
    assert good.exit_code == 0 and "3 anchors" in good.output, good.output
    data = valid()
    data["anchors"][0]["topic"] = "nope"
    broken = tmp_path / "anchors.yaml"
    broken.write_text(yaml.safe_dump(data), encoding="utf-8")
    bad = runner.invoke(app, ["taxonomy", "check", *topics_arg, "--anchors", str(broken)])
    assert bad.exit_code == 1 and "is not a topic" in bad.output
