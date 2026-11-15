"""DBLP dump reader and stream index, on a trimmed real sample (tests/fixtures/dblp/)."""

from __future__ import annotations

import gzip
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from flatatlas.cli import app
from flatatlas.dblp_dump import (
    DumpError,
    build_stream_index,
    edition_summary,
    edition_year,
    iter_records,
    load_entities,
    md5_of,
    read_index,
    stream_of,
    verify_checksum,
    write_index,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "dblp"
SAMPLE = FIXTURES / "dblp_sample.xml.gz"
DTD = FIXTURES / "dblp.dtd"
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)

HEADER = '<?xml version="1.0" encoding="ISO-8859-1"?>\n<!DOCTYPE dblp SYSTEM "dblp.dtd">\n<dblp>\n'


def write_dump(path: Path, body: str) -> Path:
    with gzip.open(path, "wt", encoding="iso-8859-1") as handle:
        handle.write(HEADER + body + "</dblp>\n")
    return path


@pytest.fixture
def index() -> dict:
    return build_stream_index(SAMPLE, DTD, ["conf/dlt", "conf/wia", "conf/dcfs"], now=lambda: NOW)


# -- reading ---------------------------------------------------------------


def test_entities_come_from_the_dtd() -> None:
    entities = load_entities(DTD)
    assert len(entities) >= 60
    assert entities["auml"] == "ä" and entities["szlig"] == "ß"


def test_entities_from_a_file_that_is_not_the_dtd_are_refused(tmp_path: Path) -> None:
    bogus = tmp_path / "x.dtd"
    bogus.write_text('<!ENTITY a "&#97;">')
    with pytest.raises(DumpError, match="entities"):
        load_entities(bogus)


def test_sample_records_are_read_with_fields() -> None:
    records = list(iter_records(SAMPLE, DTD))
    kinds = {r.tag for r in records}
    assert kinds == {"proceedings", "inproceedings", "article"}
    dlt = next(r for r in records if r.key == "conf/dlt/2019")
    assert dlt.tag == "proceedings"
    assert dlt.first("publisher") == "Springer"
    assert dlt.first("volume") == "11647"
    assert dlt.fields["isbn"] == ["978-3-030-24885-7", "978-3-030-24886-4"]
    assert dlt.first("ee") == "https://doi.org/10.1007/978-3-030-24886-4"
    paper = next(r for r in records if r.key == "conf/dlt/Massazza19")
    assert paper.first("crossref") == "conf/dlt/2019"
    assert paper.fields["author"] == ["Paolo Massazza"]


def test_key_filter_limits_what_is_returned() -> None:
    keys = [
        r.key for r in iter_records(SAMPLE, DTD, key_filter=lambda k: k.startswith("conf/wia/"))
    ]
    assert keys and all(k.startswith("conf/wia/") for k in keys)


def test_named_entities_are_resolved_through_the_dtd_map(tmp_path: Path) -> None:
    # Synthetic record (not from DBLP): exercises &uuml; and markup inside a title.
    dump = write_dump(
        tmp_path / "d.xml.gz",
        '<inproceedings key="conf/x/A1"><author>J&uuml;rgen Gro&szlig;e</author>'
        "<title>On <i>a</i> b&auml;r.</title><year>1999</year></inproceedings>\n",
    )
    (record,) = iter_records(dump, DTD)
    assert record.fields["author"] == ["Jürgen Große"]
    assert record.fields["title"] == ["On a bär."]


def test_xml_kept_for_fixtures_is_ascii_and_reparseable() -> None:
    record = next(
        iter_records(SAMPLE, DTD, key_filter=lambda k: k == "conf/wia/2019", keep_xml=True)
    )
    assert record.xml is not None and record.xml.isascii()
    assert "Ko&#353;ice" in record.xml or "Kosice" in record.xml


def test_truncated_or_empty_dump_is_an_error(tmp_path: Path) -> None:
    whole = SAMPLE.read_bytes()
    cut = tmp_path / "cut.xml.gz"
    cut.write_bytes(whole[: len(whole) // 2])
    with pytest.raises(DumpError, match="damaged or truncated|cannot read"):
        list(iter_records(cut, DTD))
    empty = write_dump(tmp_path / "empty.xml.gz", "")
    with pytest.raises(DumpError, match="no records"):
        list(iter_records(empty, DTD))
    garbage = tmp_path / "garbage.xml.gz"
    garbage.write_bytes(b"not gzip at all")
    with pytest.raises(DumpError):
        list(iter_records(garbage, DTD))


def test_checksum_is_compared_with_the_md5_file(tmp_path: Path) -> None:
    dump = tmp_path / "dblp.xml.gz"
    shutil.copy(SAMPLE, dump)
    digest = md5_of(dump)
    assert verify_checksum(dump) == digest  # no .md5 file: just computes
    (tmp_path / "dblp.xml.gz.md5").write_text(f"{digest}  dblp.xml.gz\n")
    assert verify_checksum(dump) == digest
    (tmp_path / "dblp.xml.gz.md5").write_text(f"{'0' * 32}  dblp.xml.gz\n")
    with pytest.raises(DumpError, match="does not match"):
        verify_checksum(dump)


# -- keys and years --------------------------------------------------------


def test_stream_and_edition_year_come_from_the_key() -> None:
    assert stream_of("conf/dlt/Massazza19") == "conf/dlt"
    assert stream_of("journals/iandc/Doe01") == "journals/iandc"
    assert edition_year("conf/dlt/2019", 2020) == 2019
    assert edition_year("conf/dlt/2000", 2003) == 2000  # published 2003
    assert edition_year("conf/x/Abc19", 2019) == 2019  # no year in the key: fallback
    assert edition_year("conf/x/9999", 7) == 7


# -- the index -------------------------------------------------------------


def test_index_lists_editions_by_conference_year(index: dict) -> None:
    dlt = {e["key"]: e for e in index["streams"]["conf/dlt"]["editions"]}
    assert set(dlt) == {"conf/dlt/2019", "conf/dlt/2000"}
    assert dlt["conf/dlt/2019"]["n_papers"] == 3
    assert dlt["conf/dlt/2019"]["publisher"] == "Springer"
    # Published in 2003 but a 2000 edition; DBLP files it in the DLT stream.
    assert dlt["conf/dlt/2000"]["year"] == 2000 and dlt["conf/dlt/2000"]["published_year"] == 2003
    assert index["dump"] == "dblp_sample.xml.gz"
    assert index["built_at"] == "2026-11-15T12:00:00+00:00"
    assert set(index["streams"]) == {"conf/dlt", "conf/wia", "conf/dcfs"}  # journals/ not asked for


def test_shared_stream_is_split_by_year_range(index: dict) -> None:
    assert edition_summary(index, "conf/wia")["years"] == [1999, 2019]
    wia = edition_summary(index, "conf/wia", first_year=1996, last_year=1999)
    ciaa = edition_summary(index, "conf/wia", first_year=2000)
    assert (wia["n_editions"], wia["years"], wia["n_papers"]) == (1, [1999], 2)
    assert (ciaa["n_editions"], ciaa["years"], ciaa["n_papers"]) == (1, [2019], 3)
    dcagrs = edition_summary(index, "conf/dcfs", first_year=2001, last_year=2001)
    dcfs = edition_summary(index, "conf/dcfs", first_year=2002)
    assert dcagrs["years"] == [2001] and dcfs["years"] == [2019]


def test_missing_years_and_unknown_stream(index: dict) -> None:
    summary = edition_summary(index, "conf/dlt", first_year=2000)
    assert summary["years"] == [2000, 2019]
    assert summary["missing_years"] == list(range(2001, 2019))
    assert edition_summary(index, "conf/nothing") is None


def test_edition_without_proceedings_record_comes_from_crossref(tmp_path: Path) -> None:
    # Synthetic: DBLP often has papers whose crossref has no proceedings record.
    dump = write_dump(
        tmp_path / "d.xml.gz",
        '<inproceedings key="conf/x/A97"><author>A</author><title>T.</title><year>1998</year>'
        "<crossref>conf/x/1997</crossref></inproceedings>\n"
        '<inproceedings key="conf/x/B97"><author>B</author><title>U.</title><year>1998</year>'
        "<crossref>conf/x/1997</crossref></inproceedings>\n",
    )
    index = build_stream_index(dump, DTD, ["conf/x"], now=lambda: NOW)
    (edition,) = index["streams"]["conf/x"]["editions"]
    assert edition["key"] == "conf/x/1997" and edition["year"] == 1997
    assert edition["published_year"] == 1998 and edition["n_papers"] == 2
    assert edition["has_proceedings_record"] is False
    assert edition_summary(index, "conf/x")["n_with_proceedings_record"] == 0


def test_journal_streams_report_volumes_and_years(tmp_path: Path) -> None:
    dump = write_dump(
        tmp_path / "d.xml.gz",
        '<article key="journals/j/A1"><title>T.</title><year>1999</year>'
        "<volume>5</volume></article>\n"
        '<article key="journals/j/A2"><title>U.</title><year>2001</year>'
        "<volume>7</volume></article>\n",
    )
    index = build_stream_index(dump, DTD, ["journals/j"], now=lambda: NOW)
    assert index["streams"]["journals/j"]["volumes"] == ["5", "7"]
    summary = edition_summary(index, "journals/j")
    assert (summary["n_editions"], summary["first_year"], summary["last_year"]) == (0, 1999, 2001)


def test_index_round_trips_through_json(index: dict, tmp_path: Path) -> None:
    path = write_index(index, tmp_path / "sub" / "stream_index.json")
    assert read_index(path) == index
    assert read_index(tmp_path / "missing.json") is None


# -- CLI -------------------------------------------------------------------


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    folder = root / "raw" / "dblp-dump"
    folder.mkdir(parents=True)
    shutil.copy(SAMPLE, folder / "dblp.xml.gz")
    shutil.copy(DTD, folder / "dblp.dtd")
    monkeypatch.setenv("FLATATLAS_DATA_ROOT", str(root))
    return root


def test_scan_dump_writes_the_index_and_show_reads_it(data_root: Path) -> None:
    runner = CliRunner()
    show = runner.invoke(app, ["venues", "show", "ciaa"])
    assert "DBLP editions: unknown (no index yet" in show.output

    scan = runner.invoke(app, ["venues", "scan-dump"])
    assert scan.exit_code == 0, scan.output
    assert "conf/dcfs, conf/dlt, conf/wia" in scan.output
    assert (data_root / "raw" / "dblp-dump" / "stream_index.json").exists()

    ciaa = runner.invoke(app, ["venues", "show", "ciaa"]).output
    assert "DBLP editions: 1 (2019 to 2019; 1 with a proceedings record; 3 papers)" in ciaa
    wia = runner.invoke(app, ["venues", "show", "wia"]).output
    assert "DBLP editions: 1 (1999 to 1999;" in wia


def test_scan_dump_without_files_fails_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLATATLAS_DATA_ROOT", str(tmp_path / "empty"))
    result = CliRunner().invoke(app, ["venues", "scan-dump"])
    assert result.exit_code == 1
    assert "not found" in result.output
