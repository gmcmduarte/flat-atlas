"""Cut ``dblp_sample.xml.gz`` out of the real DBLP dump (run by hand when a refresh is needed).

    uv run python tests/fixtures/dblp/make_sample.py data/raw/dblp-dump

Keeps the real ``<proceedings>`` records and the first few real papers of a handful of pilot
editions, the papers named in ``WANTED`` (the awkward cases the parser tests need), the real
person records (``<www>``) of every kept author, plus one record of another stream. Records are
written as ASCII (non-ASCII characters as numeric references), under the original ISO-8859-1
header and DOCTYPE. ``dblp.dtd`` next to this file is a copy of the DTD that came with the dump.
It also prints the titles of papers in the pilot streams that look like front matter.
"""

from __future__ import annotations

import gzip
import re
import sys
from collections import Counter
from pathlib import Path

from flatatlas.dblp_dump import iter_records, stream_of

# edition key -> number of papers to keep
EDITIONS = {
    "conf/dlt/2019": 3,
    "conf/dlt/2000": 0,  # a Kyoto colloquium DBLP files in the DLT stream; publication year 2003
    "conf/dlt/1993": 3,  # World Scientific: no DOI, no ee
    "conf/wia/2019": 3,  # CIAA 2019, Kosice
    "conf/wia/1999": 2,  # WIA'99, Potsdam
    "conf/dcfs/2019": 3,
    "conf/dcfs/2001": 2,  # DCAGRS 2001, Vienna
    # DCFS 2009 and 2010: EPTCS volumes that DBLP files under CoRR (D-51)
    "journals/corr/abs-0907-5257": 2,
    "journals/corr/abs-1008-1270": 2,
}
# papers kept in addition to the first few: a homonym-suffixed author ('Bo Cui 0001')
WANTED = {"journals/corr/abs-1008-1648"}
OTHER_STREAM = "journals/iandc"
FRONT = re.compile(
    r"^(preface|front matter|foreword|invited|tutorial|index|author index|abstracts?)\b", re.I
)

HEADER = '<?xml version="1.0" encoding="ISO-8859-1"?>\n<!DOCTYPE dblp SYSTEM "dblp.dtd">\n<dblp>\n'


def main(dump_dir: Path) -> None:
    streams = {stream_of(k) for k in EDITIONS}
    kept: dict[str, list[str]] = {}
    taken: Counter[str] = Counter()
    names: set[str] = set()  # authors of the kept papers
    people: list[str] = []
    other = None
    front: list[str] = []

    def want(key: str) -> bool:
        return (
            stream_of(key) in streams
            or key.startswith(OTHER_STREAM + "/")
            or key.startswith("homepages/")
        )

    for record in iter_records(
        dump_dir / "dblp.xml.gz", dump_dir / "dblp.dtd", key_filter=want, keep_xml=True
    ):
        if record.key.startswith("homepages/"):
            if any(n in names for n in record.fields.get("author", [])):
                people.append(record.xml or "")
            continue
        if record.key.startswith(OTHER_STREAM + "/"):
            if other is None and record.tag == "article":
                other = record.xml
            continue
        if record.tag == "proceedings" and record.key in EDITIONS:
            kept.setdefault(record.key, []).insert(0, record.xml or "")
        elif record.tag == "inproceedings":
            ref = record.first("crossref")
            if ref not in EDITIONS:
                continue
            title = record.first("title") or ""
            looks_like_front = bool(FRONT.match(title))
            if looks_like_front:
                front.append(f"{record.key}\tpages={record.first('pages')}\t{title}")
            first_few = taken[ref] < EDITIONS[ref]
            if first_few or record.key in WANTED or (looks_like_front and len(front) <= 2):
                taken[ref] += 1
                names.update(record.fields.get("author", []))
                kept.setdefault(ref, []).append(record.xml or "")
    out = Path(__file__).with_name("dblp_sample.xml.gz")
    with gzip.open(out, "wt", encoding="iso-8859-1", newline="\n") as handle:
        handle.write(HEADER)
        for key in EDITIONS:
            for xml in kept.get(key, []):
                handle.write(xml.strip() + "\n")
        if other:
            handle.write(other.strip() + "\n")
        for xml in people:
            handle.write(xml.strip() + "\n")
        handle.write("</dblp>\n")
    print(
        f"wrote {out}: {sum(len(v) for v in kept.values())} edition records, "
        f"{len(people)} person records, 1 other"
    )
    print("front-matter-looking titles in the kept editions:")
    print("\n".join(front) or "(none)")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
