"""The labelled set (P1-06b): sampling, review sheets, finalise and report."""

from __future__ import annotations

import random
from pathlib import Path

import duckdb
import pytest
import yaml
from typer.testing import CliRunner

from flatatlas.cli import app
from flatatlas.db import connect
from flatatlas.taxonomy import check as tcheck
from flatatlas.taxonomy import gold as tgold
from flatatlas.taxonomy.schema import GoldFile, GoldWork, split_for
from flatatlas.text.composite import CompositeParts

FIXTURES = Path(__file__).parent.parent / "fixtures" / "taxonomy"
VENUES = {"V1": "DLT", "V2": "CIAA", "V3": "TINY"}


def topics():
    return tcheck.load_topics(FIXTURES / "topics_valid.yaml")


def make_rows(n_per_venue: dict[str, int] | None = None) -> list[tuple]:
    """(work_id, title, year, has_abstract, venue_id): DLT and CIAA large, TINY with 2 works."""
    n_per_venue = n_per_venue or {"V1": 300, "V2": 200, "V3": 2}
    rows = []
    i = 0
    for venue, count in n_per_venue.items():
        for k in range(count):
            year = 1995 + (k * 7) % 30
            rows.append((f"W{i:010d}", f"Title {i}", year, k % 4 == 0, venue))
            i += 1
    return rows


def build_db(con: duckdb.DuckDBPyConnection, rows: list[tuple], *, with_tags: bool = False) -> None:
    con.execute(
        "CREATE TABLE core_work (work_id VARCHAR, title VARCHAR, year SMALLINT, "
        "primary_version_id VARCHAR, has_abstract BOOLEAN, scope_status VARCHAR)"
    )
    con.execute(
        "CREATE TABLE core_version (version_id VARCHAR, work_id VARCHAR, venue_id VARCHAR, "
        "doi VARCHAR, dblp_key VARCHAR, openalex_id VARCHAR, s2_corpus_id BIGINT)"
    )
    con.execute("CREATE TABLE core_venue (venue_id VARCHAR, acronym VARCHAR)")
    con.executemany("INSERT INTO core_venue VALUES (?, ?)", list(VENUES.items()))
    for wid, title, year, has_abs, venue in rows:
        vid = "P" + wid[1:]
        con.execute(
            "INSERT INTO core_work VALUES (?, ?, ?, ?, ?, 'core')", [wid, title, year, vid, has_abs]
        )
        con.execute(
            "INSERT INTO core_version VALUES (?, ?, ?, ?, ?, NULL, NULL)",
            [vid, wid, venue, f"10.1/{wid.lower()}", f"conf/x/{wid}"],
        )
    # One work out of scope: never sampled.
    con.execute("INSERT INTO core_work VALUES ('WOUTOFSCOPE1', 'Out', 2000, NULL, false, 'out')")
    if with_tags:
        con.execute("CREATE TABLE core_tag (work_id VARCHAR, topic_id VARCHAR, score DOUBLE)")
        con.execute("CREATE TABLE tag_signal (work_id VARCHAR, topic_id VARCHAR, value DOUBLE)")
        con.execute("INSERT INTO core_tag SELECT work_id, 'regular-languages', 0.9 FROM core_work")


def frame_of(rows, **kwargs):
    con = duckdb.connect()
    build_db(con, rows, **kwargs)
    return tgold.sampling_frame(con)


def draw(frame, n=60, seed=7, n_blind=10):
    return tgold.draw(frame, n=n, seed=seed, min_per_cell=3, n_blind=n_blind)


# -- sampling -------------------------------------------------------------------------------------


def test_allocate_is_proportional_with_floor_and_exact_total():
    sizes = {"a": 1000, "b": 100, "c": 2, "d": 10}
    alloc = tgold.allocate(sizes, 100, 3)
    assert sum(alloc.values()) == 100
    assert alloc["c"] == 2  # the whole cell, smaller than the floor
    assert alloc["d"] == 3  # floor, above its quota of 0.9
    assert alloc["a"] > alloc["b"] > alloc["d"]
    assert all(alloc[c] <= sizes[c] for c in sizes)


def test_allocate_refuses_impossible_requests():
    with pytest.raises(tgold.GoldError):
        tgold.allocate({"a": 5}, 6, 3)
    with pytest.raises(tgold.GoldError):
        tgold.allocate({c: 10 for c in "abcdef"}, 10, 3)


def test_sample_hits_the_quotas_and_skips_out_of_scope_works():
    frame = frame_of(make_rows())
    assert "WOUTOFSCOPE1" not in {w.work_id for w in frame}
    sample = draw(frame)
    assert len(sample.works) == 60
    got: dict[str, int] = {}
    for w in sample.works:
        got[w.cell] = got.get(w.cell, 0) + 1
    assert got == {c: k for c, k in sample.quotas.items() if k}
    for cell, size in sample.frame_counts.items():
        assert sample.quotas[cell] >= min(3, size)
    assert sum(sample.frame_counts.values()) == len(frame)
    tiny = [c for c in sample.frame_counts if c.startswith("TINY|")]
    assert tiny and all(got[c] == sample.frame_counts[c] for c in tiny)


def test_sample_is_deterministic_and_ignores_row_order():
    rows = make_rows()
    first = draw(frame_of(rows))
    shuffled = rows[:]
    random.Random(3).shuffle(shuffled)
    second = draw(frame_of(shuffled))
    assert first.works == second.works
    assert tgold.dump_sample(first) == tgold.dump_sample(second)
    assert draw(frame_of(rows), seed=8).ids() != first.ids()


def test_sample_is_unchanged_when_tag_tables_exist():
    rows = make_rows()
    assert draw(frame_of(rows)).works == draw(frame_of(rows, with_tags=True)).works


def test_blind_subset_is_deterministic_and_of_the_asked_size():
    sample = draw(frame_of(make_rows()))
    assert len(sample.blind_ids()) == 10
    assert sample.blind_ids() <= set(sample.ids())
    assert tgold.choose_blind(sample.ids(), 10, 7) == sample.blind_ids()
    order = tgold.review_order(sample)
    assert [w.blind for w in order] == [False] * 50 + [True] * 10


def test_sample_file_round_trips():
    sample = draw(frame_of(make_rows()))
    again = tgold.load_sample(tgold.dump_sample(sample))
    assert again.works == sample.works and again.quotas == sample.quotas


# -- sheets ---------------------------------------------------------------------------------------


def parts_for(frame) -> dict[str, CompositeParts]:
    return {
        w.work_id: CompositeParts(
            work_id=w.work_id,
            title=w.title,
            venue=w.venue,
            year=str(w.year),
            reference_titles=("A reference",),
            abstract="SECRET ABSTRACT TEXT" if w.has_abstract else "",
            tldr="",
            n_references=1,
            n_references_with_title=1,
            abstract_source=None,
        )
        for w in frame
    }


def test_draft_yaml_round_trips_keeps_labels_and_holds_no_abstract():
    frame = frame_of(make_rows())
    by_id = {w.work_id: w for w in frame}
    sample = draw(frame)
    draft = tgold.build_draft(sample, by_id, taxonomy_version=1)
    first = draft.works[0].work
    draft.works[0].labels = ["regular-languages", "descriptional-complexity"]
    draft.works[0].note = 'unsure: "quotes"'
    text = tgold.render_gold_yaml(draft, by_id, header=tgold.DRAFT_HEADER)
    assert "SECRET" not in text
    parsed = tcheck.parse_gold(text)
    assert parsed == draft
    assert all(w.split == split_for(w.work) for w in parsed.works)
    problems = tcheck.check_gold(parsed, topics(), resolve_work=lambda w: w)
    assert problems == []
    # A second sheet run keeps what was drafted.
    again = tgold.build_draft(sample, by_id, taxonomy_version=1, existing=parsed)
    assert again.works[0].work == first
    assert again.works[0].labels == ["regular-languages", "descriptional-complexity"]
    assert again.works[0].note == 'unsure: "quotes"'


def test_blind_sheet_lists_blind_works_only_and_parses_back():
    frame = frame_of(make_rows())
    by_id = {w.work_id: w for w in frame}
    sample = draw(frame)
    text = tgold.render_blind_md(sample, by_id, parts_for(frame), topics())
    parsed = tgold.parse_blind_md(text)
    assert set(parsed) == sample.blind_ids()
    assert all(e.labels == [] for e in parsed.values())
    assert "`regular-languages`" in text and "https://doi.org/" in text
    context = tgold.render_context_md(sample, by_id, parts_for(frame))
    assert not any(wid in context for wid in sample.blind_ids())


def test_parse_blind_accepts_three_label_syntaxes():
    text = (
        "intro\n## 1. WAAAAAAAAAA\nlabels: regular-languages, descriptional-complexity\n"
        "note: hard one\n## 2. WAAAAAAAAAB\nlabels: [context-free-languages, shuffle-of-words]\n"
        "## 3. WAAAAAAAAAC\nlabels: regular-languages  shuffle-of-words\nnote:\n"
        "## Topics\nlabels: ignored\n"
    )
    parsed = tgold.parse_blind_md(text)
    assert parsed["WAAAAAAAAAA"] == tgold.BlindEntry(
        ["regular-languages", "descriptional-complexity"], "hard one"
    )
    assert parsed["WAAAAAAAAAB"].labels == ["context-free-languages", "shuffle-of-words"]
    assert parsed["WAAAAAAAAAC"].labels == ["regular-languages", "shuffle-of-words"]
    assert set(parsed) == {"WAAAAAAAAAA", "WAAAAAAAAAB", "WAAAAAAAAAC"}


# -- finalise -------------------------------------------------------------------------------------


def gw(work: str, labels: list[str], *, blind=False, reviewed=False, note="", sampling="random"):
    return GoldWork(
        work=work,
        title="T",
        labels=labels,
        split=split_for(work),
        sampling=sampling,
        blind=blind,
        reviewed=reviewed,
        note=note,
    )


IDS = [f"W{i:010d}" for i in range(6)]


def test_finalise_keeps_labels_as_set_and_uses_blind_labels():
    draft = GoldFile(
        taxonomy_version=1,
        works=[
            gw(IDS[0], ["descriptional-complexity", "regular-languages"], note="his note"),
            gw(IDS[1], ["context-free-languages", "shuffle-of-words"]),
            gw(IDS[2], ["regular-languages"], blind=True),  # Claude's later draft: not used
        ],
    )
    blind = {IDS[2]: tgold.BlindEntry(["context-free-languages"], "blind note")}
    out = tgold.finalise(draft, blind, topics())
    by = {w.work: w for w in out.works}
    assert by[IDS[0]].labels == ["descriptional-complexity", "regular-languages"]  # order kept
    assert by[IDS[0]].note == "his note"
    assert by[IDS[2]].labels == ["context-free-languages"] and by[IDS[2]].note == "blind note"
    assert all(w.reviewed and w.split == split_for(w.work) for w in out.works)
    assert tcheck.check_gold(out, topics(), resolve_work=lambda w: w) == []


def test_finalise_keeps_reviewed_entries_byte_for_byte():
    old = gw(IDS[0], ["shuffle-of-words", "context-free-languages"], reviewed=True, note="x")
    existing = GoldFile(taxonomy_version=1, works=[old])
    before = tgold.render_gold_yaml(existing)
    draft = GoldFile(
        taxonomy_version=1,
        works=[gw(IDS[0], ["regular-languages"]), gw(IDS[1], ["regular-languages"])],
    )
    out = tgold.finalise(draft, {}, topics(), existing=existing)
    assert out.works[0] == old
    block = before.split("works:\n", 1)[1]
    assert block in tgold.render_gold_yaml(out)


@pytest.mark.parametrize(
    ("labels", "message"),
    [
        (["unary-languages", "regular-languages"], "not a level-0 or level-1 topic"),
        (["no-such-topic"], "is not a topic"),
        (["descriptional-complexity"], "no level-0 label"),
        (["context-free-languages", "descriptional-complexity"], "needs its parent"),
        ([], "no level-0 label"),
    ],
)
def test_finalise_refuses_bad_labels(labels, message):
    draft = GoldFile(taxonomy_version=1, works=[gw(IDS[0], labels)])
    with pytest.raises(tgold.GoldError) as err:
        tgold.finalise(draft, {}, topics())
    assert any(message in p for p in err.value.problems)


def test_finalise_refuses_a_missing_blind_work_and_a_held_out_topup():
    heldout = next(w for w in (f"W{i:010d}" for i in range(100)) if split_for(w) == "heldout")
    draft = GoldFile(
        taxonomy_version=1,
        works=[
            gw(IDS[0], [], blind=True),
            gw(heldout, ["regular-languages"], sampling="topup"),
        ],
    )
    with pytest.raises(tgold.GoldError) as err:
        tgold.finalise(draft, {}, topics())
    text = " ".join(err.value.problems)
    assert "missing from gold-blind.md" in text and "top-up" in text


# -- report ---------------------------------------------------------------------------------------


def test_report_counts_changes_and_blind_agreement():
    draft = GoldFile(
        taxonomy_version=1,
        works=[
            gw(IDS[0], ["regular-languages", "descriptional-complexity"]),
            gw(IDS[1], ["regular-languages"], blind=True),
        ],
    )
    gold = GoldFile(
        taxonomy_version=1,
        works=[
            gw(IDS[0], ["regular-languages"], reviewed=True),
            gw(IDS[1], ["regular-languages", "context-free-languages"], blind=True, reviewed=True),
        ],
    )
    text = tgold.render_report(gold, draft, topics())
    assert "| 1 | 1 | 0 | 1 | 0 | 100.0% |" in text  # the level-1 draft label was removed
    assert "Jaccard per work: mean 0.50" in text
    assert "| 0 | 1.00 | 0.50 | 1 | 1 | 2 |" in text  # level-0 precision and recall


# -- commands -------------------------------------------------------------------------------------


def add_text_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE TABLE local_work_abstract (work_id VARCHAR, source VARCHAR, text VARCHAR)")
    con.execute("CREATE TABLE stg_s2_paper (s2_corpus_id BIGINT, tldr VARCHAR)")
    con.execute(
        "CREATE TABLE stg_reference_title (openalex_id VARCHAR, title VARCHAR, source VARCHAR, "
        "type VARCHAR)"
    )
    con.execute(
        "CREATE TABLE stg_openalex_reference "
        "(citing_openalex_id VARCHAR, cited_openalex_id VARCHAR)"
    )


def test_sample_and_sheet_commands(settings, monkeypatch, tmp_path):
    monkeypatch.setattr("flatatlas.taxonomy.gold_commands.load_settings", lambda **_: settings)
    con = connect(settings.paths)
    build_db(con, make_rows({"V1": 400, "V2": 300, "V3": 2}))
    add_text_tables(con)
    con.close()
    runner = CliRunner()
    result = runner.invoke(app, ["gold", "sample", "--n", "120"])
    assert result.exit_code == 0, result.output
    sample_file = settings.paths.review / "gold-sample.yaml"
    first = sample_file.read_text()
    assert runner.invoke(app, ["gold", "sample", "--n", "120"]).exit_code == 0
    assert sample_file.read_text() == first
    data = yaml.safe_load(first)
    assert len(data["works"]) == 120 and sum(w["blind"] for w in data["works"]) == 50

    draft = tmp_path / "gold-draft.yaml"
    result = runner.invoke(app, ["gold", "sheet", "--draft", str(draft)])
    assert result.exit_code == 0, result.output
    parsed = tcheck.load_gold(draft)
    assert len(parsed.works) == 120
    assert (settings.paths.review / "gold-blind.md").exists()
    assert (settings.paths.review / "gold-context.md").exists()
    con = connect(settings.paths, read_only=True)
    stages = {r[0] for r in con.execute("SELECT stage FROM ops_run_log").fetchall()}
    counts = con.execute(
        "SELECT counts FROM ops_run_log WHERE stage = 'gold-sample' LIMIT 1"
    ).fetchone()[0]
    con.close()
    assert {"gold-sample", "gold-sheet"} <= stages
    assert '"seed": 20261118' in counts and "frame_counts" in counts
