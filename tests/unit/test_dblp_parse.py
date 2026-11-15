"""The DBLP parse stage (P1-01) on a trimmed real sample (tests/fixtures/dblp/)."""

from __future__ import annotations

import gzip
import shutil
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from flatatlas.cli import app
from flatatlas.dblp_dump import build_stream_index
from flatatlas.sources import dblp
from flatatlas.venues import Venue, VenueConfigError, find_problems, load_venues, parse_venues

FIXTURES = Path(__file__).parent.parent / "fixtures" / "dblp"
SAMPLE = FIXTURES / "dblp_sample.xml.gz"
DTD = FIXTURES / "dblp.dtd"
HEADER = '<?xml version="1.0" encoding="ISO-8859-1"?>\n<!DOCTYPE dblp SYSTEM "dblp.dtd">\n<dblp>\n'


@pytest.fixture(scope="module")
def registry():
    return load_venues()


@pytest.fixture(scope="module")
def parsed(registry) -> dblp.ParsedDblp:
    venues = dblp.select_venues(registry, "all", None)
    return dblp.parse_dump(SAMPLE, DTD, venues, dblp.load_rules())


def venue(venue_id: str, stream: str, **kw) -> Venue:
    return Venue(
        id=venue_id, acronym=venue_id.upper(), name=venue_id, kind="conference", tier="core",
        dblp_stream=stream, **kw,
    )  # fmt: skip


def write_dump(path: Path, body: str) -> Path:
    with gzip.open(path, "wt", encoding="iso-8859-1") as handle:
        handle.write(HEADER + body + "</dblp>\n")
    return path


# -- titles ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "shown", "norm"),
    [
        ("Hole-Free Partially Directed Animals.", "Hole-Free Partially Directed Animals",
         "hole free partially directed animals"),
        ("Gröbner Bases for Étale Maps.", "Gröbner Bases for Étale Maps",
         "grobner bases for etale maps"),
        ("On $\\omega$-Regular \\emph{Tree} Languages.",
         "On $\\omega$-Regular \\emph{Tree} Languages", "on regular tree languages"),
        ("The {\\\"o}ther  {\\'e}cole", "The {\\\"o}ther {\\'e}cole", "the other ecole"),
        ("What is a word...", "What is a word...", "what is a word"),
        ("  Spaces \n inside. ", "Spaces inside", "spaces inside"),
    ],
)  # fmt: skip
def test_titles_are_cleaned_and_normalised(raw: str, shown: str, norm: str) -> None:
    assert dblp.clean_title(raw) == shown
    assert dblp.normalize_title(raw) == norm


def test_homonym_suffix_is_not_part_of_the_display_name() -> None:
    assert dblp.display_name("Bo Cui 0001") == "Bo Cui"
    assert dblp.display_name("Lila Kari") == "Lila Kari"
    assert dblp.display_name("Louis 14 Paul") == "Louis 14 Paul"


def test_dois_come_from_ee_links_and_prefer_the_publishers() -> None:
    ee = [
        "https://doi.org/10.48550/arXiv.0907.5127",
        "https://doi.org/10.4204/EPTCS.3.12",
        "http://www.worldscibooks.com/compsci/4959.html",
    ]
    dois = dblp.extract_dois(ee)
    assert dois == ["10.48550/arxiv.0907.5127", "10.4204/eptcs.3.12"]
    assert dblp.preferred_doi(dois) == "10.4204/eptcs.3.12"
    assert dblp.preferred_doi(dois[:1]) == "10.48550/arxiv.0907.5127"  # arXiv only as a fallback
    assert dblp.preferred_doi([]) is None


# -- front matter ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "pages", "flagged"),
    [
        ("Front Matter", None, True),
        ("Preface.", "V-VI", True),
        ("Preface to the Special Issue", None, True),
        ("Author Index", None, True),
        ("Invited talk abstracts", None, True),
        ("Invited Talk: Two-Way Automata", "1-20", False),  # with pages it is a paper
        ("Invited Talk", None, True),
        ("Introduction to Weighted Automata", "1-10", False),  # only the exact title is flagged
        ("Hole-Free Partially Directed Animals", "223-234", False),
    ],
)
def test_front_matter_rules_come_from_the_config_file(title, pages, flagged) -> None:
    rule = dblp.load_rules().classify(title, pages)
    assert (rule is not None) is flagged
    if flagged:
        assert rule.split(":")[0] in {"title", "pattern", "no-pages"}


def test_front_matter_rules_are_data_not_code() -> None:
    rules = dblp.parse_rules({"front_matter_titles": ["Colophon"]})
    assert rules.classify("Colophon.", None) == "title:colophon"
    assert rules.classify("Preface", None) is None  # not in this config


# -- the sample -----------------------------------------------------------------------------------


def test_editions_are_routed_to_venues_by_stream_and_year(parsed: dblp.ParsedDblp) -> None:
    editions = {e["edition_key"]: e for e in parsed.editions}
    assert {k: (e["venue_id"], e["year"]) for k, e in editions.items()} == {
        "conf/dlt/1993": ("dlt", 1993),
        "conf/dlt/2019": ("dlt", 2019),
        "conf/wia/1999": ("wia", 1999),  # the shared stream: WIA ...
        "conf/wia/2019": ("ciaa", 2019),  # ... and CIAA
        "conf/dcfs/2001": ("dcagrs", 2001),  # the shared stream: DCAGRS ...
        "conf/dcfs/2019": ("dcfs", 2019),  # ... and DCFS
        "journals/corr/abs-0907-5257": ("dcfs", 2009),  # DCFS 2009 and 2010 live under CoRR
        "journals/corr/abs-1008-1270": ("dcfs", 2010),
    }
    # The edition year is the key's, not the record's (publication) year.
    assert editions["conf/dlt/1993"]["published_year"] == 1994
    assert editions["conf/wia/1999"]["published_year"] == 2001
    assert editions["conf/dlt/2019"]["label"] == "DLT 2019"
    assert editions["conf/dlt/2019"]["proceedings_doi"] == "10.1007/978-3-030-24886-4"
    assert editions["conf/dlt/2019"]["isbns"] == ["978-3-030-24885-7", "978-3-030-24886-4"]
    assert editions["conf/dlt/2019"]["publisher"] == "Springer"
    assert editions["journals/corr/abs-0907-5257"]["series"] == "EPTCS"
    assert editions["journals/corr/abs-0907-5257"]["source"] == "extra"
    assert editions["conf/dcfs/2001"]["proceedings_doi"] is None


def test_an_excluded_edition_is_left_out(parsed: dblp.ParsedDblp) -> None:
    # DBLP files another meeting's proceedings as conf/dlt/2000; venues.yaml excludes it.
    assert "conf/dlt/2000" not in {e["edition_key"] for e in parsed.editions}
    assert parsed.stats["editions_excluded"] == 1


def test_papers_per_edition_are_counted_and_linked(parsed: dblp.ParsedDblp) -> None:
    per_edition = {e["edition_key"]: e["n_papers"] for e in parsed.editions}
    assert per_edition["conf/dlt/2019"] == 3
    assert per_edition["journals/corr/abs-1008-1270"] == 3  # 2 first ones + the homonym case
    assert sum(per_edition.values()) == len(parsed.papers) == 21
    assert {p["edition_key"] for p in parsed.papers} == set(per_edition)
    corr = next(p for p in parsed.papers if p["dblp_key"] == "journals/corr/abs-0907-5127")
    assert corr["venue_id"] == "dcfs" and corr["edition_year"] == 2009
    assert corr["doi"] == "10.4204/eptcs.3.12"  # not the arXiv DOI
    assert "10.48550/arxiv.0907.5127" in corr["dois"]


def test_a_paper_without_doi_keeps_a_null_doi(parsed: dblp.ParsedDblp) -> None:
    paper = next(p for p in parsed.papers if p["dblp_key"] == "conf/dlt/Raz93")
    assert paper["title"].startswith("Deciding Multiplicity Equivalence")
    assert not paper["title"].endswith(".")
    assert paper["type"] == "inproceedings" and paper["pages"]


def test_homonym_author_gets_the_pid_of_the_numbered_person(parsed: dblp.ParsedDblp) -> None:
    rows = [a for a in parsed.authorships if a["dblp_key"] == "journals/corr/abs-1008-1648"]
    assert [r["name_raw"] for r in rows] == [
        "Bo Cui 0001", "Yuan Gao 0001", "Lila Kari", "Sheng Yu 0001",
    ]  # fmt: skip
    assert [r["position"] for r in rows] == [1, 2, 3, 4]
    assert rows[0]["pid"] == "58/4730-1"
    assert all(r["pid"] for r in rows)
    authors = {a["pid"]: a for a in parsed.authors}
    assert authors["58/4730-1"]["name"] == "Bo Cui"  # suffix stripped for display
    assert "Bo Cui 0001" in authors["58/4730-1"]["name_variants"]  # printed form kept


def test_every_name_has_a_pid_and_orcids_are_read(parsed: dblp.ParsedDblp) -> None:
    assert parsed.stats["names_without_pid"] == 0 and parsed.stats["names_ambiguous"] == 0
    by_pid = {a["pid"]: a for a in parsed.authors}
    assert len(by_pid) == parsed.stats["authors"]
    # an ORCID from the <www> record's url, and one from the paper's <author orcid=...>
    assert by_pid["32/3049-1"]["orcid"] == "0000-0003-1955-4225"
    assert sum(1 for a in parsed.authors if a["orcid"]) >= 5
    samavati = next(a for a in parsed.authors if a["name"] == "Faramarz F. Samavati")
    assert samavati["orcid"] == "0000-0001-9440-7562"
    assert "Faramarz Samavati" in samavati["name_variants"]


def test_front_matter_is_flagged_in_the_rows(parsed: dblp.ParsedDblp) -> None:
    assert all(
        p["is_front_matter"] is False and p["front_matter_rule"] is None for p in parsed.papers
    )


def test_the_count_check_agrees_with_the_stream_index(parsed, registry) -> None:
    index = build_stream_index(
        SAMPLE, DTD, ["conf/dlt", "conf/wia", "conf/dcfs"],
        now=lambda: datetime(2026, 11, 15, tzinfo=UTC),
    )  # fmt: skip
    rows = dblp.compare_with_index(parsed, index, registry.venues)
    status = {r["edition_key"]: r["status"] for r in rows}
    assert {s for k, s in status.items() if not k.startswith("journals/")} == {"ok"}
    assert status["journals/corr/abs-0907-5257"] == "not indexed"  # outside the indexed streams


def test_doi_share_per_venue_and_decade(parsed: dblp.ParsedDblp) -> None:
    rows = {(r["venue_id"], r["decade"]): r for r in dblp.doi_share(parsed)}
    assert rows[("dlt", 1990)]["with_doi"] == 0 and rows[("dlt", 1990)]["papers"] == 3
    assert rows[("dlt", 2010)]["share"] == 1.0
    assert rows[("dcfs", 2000)]["with_doi"] == 2  # the EPTCS papers of 2009


def test_sample_rows_are_reproducible(parsed: dblp.ParsedDblp) -> None:
    first = dblp.sample_rows(parsed, 5)
    assert [r["dblp_key"] for r in first] == [r["dblp_key"] for r in dblp.sample_rows(parsed, 5)]
    assert all(r["authors"] for r in first)


# -- awkward synthetic cases ----------------------------------------------------------------------


def person_first_dump(tmp_path: Path) -> Path:
    # Synthetic: person records BEFORE the papers (not how DBLP orders them) -> second pass.
    return write_dump(
        tmp_path / "d.xml.gz",
        '<www key="homepages/a/AnnA"><author>Ann A</author><title>Home Page</title></www>\n'
        '<www key="homepages/b/BobB"><author>Bob B 0001</author><author>Robert B</author>'
        "<title>Home Page</title></www>\n"
        '<proceedings key="conf/dlt/2001"><title>DLT 2001.</title><year>2002</year>'
        "</proceedings>\n"
        '<inproceedings key="conf/dlt/AB01"><author>Ann A</author><author>Bob B 0001</author>'
        "<title>A title.</title><pages>1-9</pages><year>2001</year>"
        "<crossref>conf/dlt/2001</crossref></inproceedings>\n",
    )


def test_person_records_before_the_papers_trigger_a_second_pass(tmp_path: Path) -> None:
    result = dblp.parse_dump(
        person_first_dump(tmp_path),
        DTD,
        [venue("dlt", "conf/dlt", first_year=1993)],
        dblp.load_rules(),
    )
    assert result.notes["second_pass"] is True
    assert [a["pid"] for a in result.authorships] == ["a/AnnA", "b/BobB"]


def test_an_unknown_or_ambiguous_name_gets_no_pid(tmp_path: Path) -> None:
    dump = write_dump(
        tmp_path / "d.xml.gz",
        '<proceedings key="conf/dlt/2001"><title>DLT.</title><year>2001</year></proceedings>\n'
        '<inproceedings key="conf/dlt/X01"><author>Ann A</author><author>Cy C</author>'
        "<author>Dee D</author><title>T.</title><year>2001</year>"
        "<crossref>conf/dlt/2001</crossref></inproceedings>\n"
        '<www key="homepages/a/1"><author>Ann A</author><title>Home Page</title></www>\n'
        '<www key="homepages/a/2"><author>Ann A</author><title>Home Page</title></www>\n'
        '<www key="homepages/d/D"><author>Dee D</author><title>Home Page</title></www>\n',
    )
    result = dblp.parse_dump(
        dump, DTD, [venue("dlt", "conf/dlt", first_year=1993)], dblp.load_rules()
    )
    assert result.notes["second_pass"] is False
    pids = {a["name_raw"]: a["pid"] for a in result.authorships}
    assert pids == {"Ann A": None, "Cy C": None, "Dee D": "d/D"}
    assert result.stats["names_ambiguous"] == 1 and result.stats["names_without_pid"] == 2


def test_an_edition_known_only_from_crossref_is_still_an_edition(tmp_path: Path) -> None:
    dump = write_dump(
        tmp_path / "d.xml.gz",
        '<inproceedings key="conf/dlt/X05"><author>Ann A</author><title>T.</title>'
        "<year>2006</year><crossref>conf/dlt/2005</crossref></inproceedings>\n",
    )
    result = dblp.parse_dump(
        dump, DTD, [venue("dlt", "conf/dlt", first_year=1993)], dblp.load_rules()
    )
    (edition,) = result.editions
    assert edition["edition_key"] == "conf/dlt/2005" and edition["year"] == 2005
    assert edition["has_proceedings_record"] is False and edition["title"] is None
    assert edition["published_year"] == 2006


def test_a_paper_outside_every_year_range_is_reported_not_guessed(tmp_path: Path) -> None:
    dump = write_dump(
        tmp_path / "d.xml.gz",
        '<inproceedings key="conf/wia/X96"><author>Ann A</author><title>T.</title>'
        "<year>1996</year><crossref>conf/wia/1996</crossref></inproceedings>\n",
    )
    only_ciaa = venue("ciaa", "conf/wia", first_year=2000)
    result = dblp.parse_dump(dump, DTD, [only_ciaa], dblp.load_rules())
    assert result.papers == [] and result.stats["papers_unassigned"] == 1
    assert result.notes["unassigned_papers"] == ["conf/wia/X96"]


# -- venue selection and the config ---------------------------------------------------------------


def test_selection_adds_predecessors_and_keeps_registry_order(registry) -> None:
    ids = [v.id for v in dblp.select_venues(registry, ["dcfs", "dlt", "ciaa"], None)]
    assert ids == ["dlt", "wia", "ciaa", "dcagrs", "dcfs"]
    assert [v.id for v in dblp.select_venues(registry, ["dcfs"], "dlt")] == ["dlt"]
    with pytest.raises(KeyError):
        dblp.select_venues(registry, "all", "nope")


def test_an_unverified_venue_is_refused(registry) -> None:
    raw = [v.model_dump(mode="json") for v in registry.venues]
    raw[0]["verified"] = {"dblp": None, "openalex": None}
    with pytest.raises(ValueError, match="D-48"):
        dblp.select_venues(parse_venues(raw), "all", None)


def test_extra_and_excluded_editions_are_validated() -> None:
    bad = venue(
        "dcfs", "conf/dcfs",
        extra_editions=[
            {"key": "conf/dcfs/2009", "year": 2009},  # already inside the venue's own stream
            {"key": "journals/corr/abs-1", "year": 2009},
            {"key": "journals/corr/abs-1", "year": 2009},  # listed twice
        ],
        excluded_editions=["conf/other/2000"],  # not in the venue's stream
    )  # fmt: skip
    problems = " | ".join(find_problems([bad]))
    assert "already in its own stream" in problems
    assert "listed twice" in problems
    assert "is not in conf/dcfs" in problems
    with pytest.raises(VenueConfigError):
        parse_venues([bad.model_dump(mode="json") | {"dblp_stream": None}])


def test_the_real_config_lists_the_dcfs_corr_volumes(registry) -> None:
    dcfs = registry.get("dcfs")
    assert [(e.key, e.year) for e in dcfs.extra_editions] == [
        ("journals/corr/abs-0907-5257", 2009),
        ("journals/corr/abs-1008-1270", 2010),
    ]
    assert registry.get("dlt").excluded_editions == ["conf/dlt/2000"]


# -- the command ----------------------------------------------------------------------------------


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    folder = root / "raw" / "dblp-dump"
    folder.mkdir(parents=True)
    shutil.copy(SAMPLE, folder / "dblp.xml.gz")
    shutil.copy(DTD, folder / "dblp.dtd")
    monkeypatch.setenv("FLATATLAS_DATA_ROOT", str(root))
    return root


def test_parse_dblp_writes_the_tables_and_logs_the_dump(data_root: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["venues", "scan-dump"]).exit_code == 0
    result = runner.invoke(app, ["parse", "dblp"])
    assert result.exit_code == 0, result.output
    assert "venues: dlt, wia, ciaa, dcagrs, dcfs" in result.output
    assert "editions 8, papers 21" in result.output
    assert "8 editions match" not in result.output  # two extra editions are not in the index
    assert "6 editions match, 0 differ, 2 not in the index" in result.output

    con = duckdb.connect(str(data_root / "warehouse" / "flatatlas.duckdb"), read_only=True)
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in dblp.TABLES}
    assert counts == {
        "stg_dblp_edition": 8,
        "stg_dblp_paper": 21,
        "stg_dblp_authorship": 42,
        "stg_dblp_author": 39,
    }
    stage, status, logged = con.execute(
        "SELECT stage, status, counts FROM ops_run_log WHERE stage = 'parse-dblp'"
    ).fetchone()
    assert (stage, status) == ("parse-dblp", "ok")
    assert "dump_md5" in logged and "dump_file_date" in logged and "newest_mdate" in logged
    con.close()
    for table in dblp.TABLES:
        assert (data_root / "warehouse" / "staging" / f"{table}.parquet").exists()


def test_parse_dblp_for_one_venue_and_its_predecessors(data_root: Path) -> None:
    result = CliRunner().invoke(app, ["parse", "dblp", "--venue", "dlt"])
    assert result.exit_code == 0, result.output
    assert "venues: dlt\n" in result.output
    assert "editions 2, papers 6" in result.output
    # no index file yet: the count check is skipped, not failed
    assert "count check skipped" in result.output


def test_parse_dblp_rerun_replaces_the_tables(data_root: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["parse", "dblp"]).exit_code == 0
    assert runner.invoke(app, ["parse", "dblp", "--venue", "dlt"]).exit_code == 0
    con = duckdb.connect(str(data_root / "warehouse" / "flatatlas.duckdb"), read_only=True)
    assert con.execute("SELECT count(*) FROM stg_dblp_paper").fetchone()[0] == 6
    assert (
        con.execute("SELECT count(*) FROM ops_run_log WHERE stage='parse-dblp'").fetchone()[0] == 2
    )
    con.close()


def test_parse_dblp_errors_are_clear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLATATLAS_DATA_ROOT", str(tmp_path / "empty"))
    runner = CliRunner()
    missing = runner.invoke(app, ["parse", "dblp"])
    assert missing.exit_code == 1 and "not found" in missing.output
    unknown = runner.invoke(app, ["parse", "dblp", "--venue", "nope"])
    assert unknown.exit_code == 1 and "Unknown venue" in unknown.output
