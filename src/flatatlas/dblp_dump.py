"""Reading the DBLP XML dump (``dblp.xml.gz`` + ``dblp.dtd``) as a stream.

Why a dump: since 2026-11 the DBLP web API answers scripts with a bot challenge (D-49, D-50), so
DBLP data comes from the official dump that Guilherme downloads by hand into
``data/raw/dblp-dump/`` (git-ignored). Metadata only, CC0 (CLAUDE.md rule 2).

The file is about 1 GB compressed and 5 GB of XML. It is never decompressed to disk: records are
read through ``gzip`` and ``xml.etree`` one at a time. The dump's DOCTYPE points at an external
DTD that defines named entities (``&uuml;``). The DTD is **not** loaded by the parser; the
entities are read from it with a regular expression and handed to the parser as a plain
dictionary, so no external resource is ever resolved.

``build_stream_index`` condenses the dump into a small JSON file for the streams named in
``config/venues.yaml``: editions (proceedings records), record counts per year and, for journals,
volumes. ``flatatlas venues scan-dump`` writes it and ``venues show`` reads it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flatatlas.db import write_text_atomic

DUMP_FILE = "dblp.xml.gz"
DTD_FILE = "dblp.dtd"
INDEX_FILE = "stream_index.json"

RECORD_TAGS = frozenset(
    {
        "article",
        "inproceedings",
        "proceedings",
        "book",
        "incollection",
        "phdthesis",
        "mastersthesis",
        "www",
        "person",
        "data",
    }
)

_ENTITY = re.compile(r'<!ENTITY\s+([A-Za-z][A-Za-z0-9]*)\s+"&#(\d+);"\s*>')


class DumpError(RuntimeError):
    """The dump is missing, damaged, or does not look like a DBLP dump."""


def load_entities(dtd_path: Path) -> dict[str, str]:
    """Named character entities of ``dblp.dtd`` (``{"auml": "ä", ...}``)."""
    text = dtd_path.read_text(encoding="iso-8859-1")
    entities = {name: chr(int(code)) for name, code in _ENTITY.findall(text)}
    if len(entities) < 50:
        raise DumpError(f"{dtd_path}: only {len(entities)} entities found; is this dblp.dtd?")
    return entities


def md5_of(path: Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def verify_checksum(dump_path: Path) -> str:
    """Compare the dump with ``<dump>.md5`` if it exists. Returns the MD5; raises on mismatch."""
    actual = md5_of(dump_path)
    md5_file = dump_path.with_name(dump_path.name + ".md5")
    if md5_file.exists():
        expected = md5_file.read_text().split()[0].lower()
        if expected != actual:
            raise DumpError(f"{dump_path.name}: MD5 {actual} does not match {md5_file.name}")
    return actual


@dataclass
class Record:
    """One top-level DBLP record. ``fields`` maps a child tag to its text values (in order)."""

    tag: str
    key: str
    mdate: str | None
    fields: dict[str, list[str]] = field(default_factory=dict)
    xml: str | None = None  # the record as ASCII XML, non-ASCII as &#NNN; (only with ``keep_xml``)
    # XML attributes of each value in ``fields``, same order and length: ``attrs["author"][0]`` is
    # the attribute dict of ``fields["author"][0]`` (``{"orcid": "0000-..."}``, ``{"type": "oa"}``).
    attrs: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    def first(self, name: str) -> str | None:
        values = self.fields.get(name)
        return values[0] if values else None

    def with_attrs(self, name: str) -> list[tuple[str, dict[str, str]]]:
        """``(text, attributes)`` for every value of a child tag, in order."""
        values = self.fields.get(name, [])
        attributes = self.attrs.get(name) or [{} for _ in values]
        return list(zip(values, attributes, strict=True))


def _record_from(elem: ET.Element, keep_xml: bool) -> Record:
    fields: dict[str, list[str]] = defaultdict(list)
    attrs: dict[str, list[dict[str, str]]] = defaultdict(list)
    for child in elem:
        text = "".join(child.itertext()).strip()
        if text:
            fields[child.tag].append(text)
            attrs[child.tag].append(dict(child.attrib))
    xml = ET.tostring(elem, encoding="us-ascii").decode("ascii") if keep_xml else None
    return Record(elem.tag, elem.get("key", ""), elem.get("mdate"), dict(fields), xml, dict(attrs))


def iter_records(
    dump_path: Path,
    dtd_path: Path,
    *,
    key_filter: Callable[[str], bool] | None = None,
    progress: Callable[[int], None] | None = None,
    keep_xml: bool = False,
) -> Iterator[Record]:
    """Stream the records of the dump whose key passes ``key_filter`` (all if None).

    ``progress`` is called with the number of records read so far, every 100,000 records.
    ``keep_xml`` also keeps each yielded record as XML text (for test fixtures).
    Memory stays flat: finished records are cleared and detached from the root.
    """
    parser = ET.XMLParser(encoding="iso-8859-1")
    parser.entity.update(load_entities(dtd_path))
    with gzip.open(dump_path, "rb") as handle:
        events = ET.iterparse(handle, events=("start", "end"), parser=parser)
        try:
            _, root = next(events)
        except (StopIteration, ET.ParseError, OSError, EOFError) as exc:
            raise DumpError(f"{dump_path}: cannot read the start of the dump ({exc})") from None
        n = 0
        try:
            for event, elem in events:
                if event != "end" or elem.tag not in RECORD_TAGS:
                    continue
                n += 1
                key = elem.get("key", "")
                if key_filter is None or key_filter(key):
                    yield _record_from(elem, keep_xml)
                elem.clear()
                if n % 5000 == 0:
                    root.clear()
                    if progress and n % 100_000 == 0:
                        progress(n)
        except (ET.ParseError, OSError, EOFError) as exc:
            raise DumpError(
                f"{dump_path}: damaged or truncated after {n} records ({exc})"
            ) from None
    if n == 0:
        raise DumpError(f"{dump_path}: no records found")


# -- the stream index -----------------------------------------------------------------------------


def stream_of(key: str) -> str:
    """``conf/dlt/2019`` and ``conf/dlt/Doe19`` both belong to stream ``conf/dlt``."""
    parts = key.split("/")
    return "/".join(parts[:2])


_KEY_YEAR = re.compile(r"^(?:19|20)\d\d$")


def edition_year(key: str, fallback: int | None) -> int | None:
    """Year of the conference edition: the key's last part (``conf/dlt/2019``), else ``fallback``.

    The ``year`` of a proceedings record is the year of *publication* and often differs
    (``conf/dlt/2025`` has year 2026), so it is only used when the key carries no year.
    """
    last = key.rsplit("/", 1)[-1]
    return int(last) if _KEY_YEAR.match(last) else fallback


def _year(record: Record) -> int | None:
    value = record.first("year")
    return int(value) if value and value.isdigit() else None


def build_stream_index(
    dump_path: Path,
    dtd_path: Path,
    streams: Iterable[str],
    *,
    progress: Callable[[int], None] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Summarise the given DBLP streams (e.g. ``conf/dlt``, ``journals/iandc``).

    An *edition* of a conference stream is a ``proceedings`` record **or** a key that papers cite
    in ``crossref``: a safeguard for an edition whose proceedings record is missing but whose
    papers still point at its key (every edition of the pilot streams has a record).

    Per edition: key, year (of the conference, from the key), published_year, number of papers,
    whether a proceedings record exists, and its title, publisher, series, volume, ISBNs, link.
    Per stream also ``records_by_year`` (all records except proceedings) and ``volumes``
    (distinct ``volume`` values of journal articles). Everything is JSON-serialisable.
    """
    wanted = frozenset(streams)
    procs: dict[str, dict[str, Any]] = {}  # proceedings key -> metadata
    paper_years: dict[str, Counter[int]] = defaultdict(Counter)  # edition key -> paper years
    by_year: dict[str, Counter[int]] = {s: Counter() for s in wanted}
    volumes: dict[str, set[str]] = {s: set() for s in wanted}
    total = 0
    newest = ""
    for record in iter_records(
        dump_path,
        dtd_path,
        key_filter=lambda key: stream_of(key) in wanted,
        progress=progress,
    ):
        stream = stream_of(record.key)
        if record.tag == "proceedings":
            procs[record.key] = {
                "year": _year(record),
                "title": record.first("title"),
                "booktitle": record.first("booktitle"),
                "publisher": record.first("publisher"),
                "series": record.first("series"),
                "volume": record.first("volume"),
                "isbn": record.fields.get("isbn", []),
                "ee": record.first("ee"),
                "mdate": record.mdate,
            }
        else:
            year = _year(record)
            if year is not None:
                by_year[stream][year] += 1
            crossref = record.first("crossref")
            if crossref and year is not None:
                paper_years[crossref][year] += 1
            if record.tag == "article" and record.first("volume"):
                volumes[stream].add(record.first("volume") or "")
        total += 1
        newest = max(newest, record.mdate or "")

    edition_keys = {k for k in (*procs, *paper_years) if stream_of(k) in wanted}
    streams_out: dict[str, Any] = {}
    for stream in sorted(wanted):
        editions = []
        for key in sorted(k for k in edition_keys if stream_of(k) == stream):
            meta = procs.get(key, {})
            years = paper_years.get(key, Counter())
            published = meta.get("year") or (years.most_common(1)[0][0] if years else None)
            editions.append(
                {
                    "key": key,
                    "year": edition_year(key, published),
                    "published_year": published,
                    "n_papers": sum(years.values()),
                    "has_proceedings_record": key in procs,
                    **{k: v for k, v in meta.items() if k != "year"},
                }
            )
        editions.sort(key=lambda e: (e["year"] or 0, e["key"]))
        streams_out[stream] = {
            "editions": editions,
            "records_by_year": {str(y): n for y, n in sorted(by_year[stream].items())},
            "volumes": sorted(volumes[stream]),
            "n_records": sum(by_year[stream].values())
            + sum(1 for k in procs if stream_of(k) == stream),
        }

    return {
        "built_at": now().isoformat(timespec="seconds"),
        "dump": dump_path.name,
        "dump_md5": md5_of(dump_path),
        "dump_size_bytes": dump_path.stat().st_size,
        "newest_mdate_in_selected_records": newest,
        "streams": streams_out,
        "n_selected_records": total,
    }


def write_index(index: dict[str, Any], path: Path) -> Path:
    write_text_atomic(path, json.dumps(index, indent=1, sort_keys=True, ensure_ascii=False))
    return path


def read_index(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def edition_summary(
    index: dict[str, Any],
    stream: str,
    *,
    first_year: int | None = None,
    last_year: int | None = None,
) -> dict[str, Any] | None:
    """What the index says about a stream, optionally limited to editions in a year range.

    The range lets two venues share one DBLP stream (WIA and CIAA are both ``conf/wia``).
    Returns None if the stream is not in the index. ``missing_years`` are the years without an
    edition between the first and the last one found (a gap in DBLP, or a year without a
    meeting).
    """
    info = index.get("streams", {}).get(stream)
    if info is None:
        return None
    editions = [
        e
        for e in info["editions"]
        if e["year"] is not None
        and (first_year is None or e["year"] >= first_year)
        and (last_year is None or e["year"] <= last_year)
    ]
    years = sorted({e["year"] for e in editions})
    if not editions:  # a journal: no editions, but records by year
        years = sorted(
            int(y)
            for y in info["records_by_year"]
            if (first_year is None or int(y) >= first_year)
            and (last_year is None or int(y) <= last_year)
        )
    return {
        "n_editions": len(editions),
        "n_with_proceedings_record": sum(1 for e in editions if e["has_proceedings_record"]),
        "n_papers": sum(e["n_papers"] for e in editions),
        "first_year": years[0] if years else None,
        "last_year": years[-1] if years else None,
        "years": years,
        "missing_years": (
            [y for y in range(years[0], years[-1] + 1) if y not in years] if editions else []
        ),
        "n_records": info["n_records"],
    }
