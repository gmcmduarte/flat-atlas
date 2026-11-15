"""Cut ``dblp_sample.xml.gz`` out of the real DBLP dump (run by hand when a refresh is needed).

    uv run python tests/fixtures/dblp/make_sample.py data/raw/dblp-dump

Keeps the real ``<proceedings>`` records and the first few real papers of a handful of pilot
editions, plus one record of another stream. Records are written as ASCII (non-ASCII characters
as numeric references), under the original ISO-8859-1 header and DOCTYPE. ``dblp.dtd`` next to
this file is a copy of the DTD that came with the dump.
"""

from __future__ import annotations

import gzip
import sys
from collections import Counter
from pathlib import Path

from flatatlas.dblp_dump import iter_records, stream_of

# edition key -> number of papers to keep
EDITIONS = {
    "conf/dlt/2019": 3,
    "conf/dlt/2000": 0,  # a Kyoto colloquium DBLP files in the DLT stream; publication year 2003
    "conf/wia/2019": 3,  # CIAA 2019, Kosice
    "conf/wia/1999": 2,  # WIA'99, Potsdam
    "conf/dcfs/2019": 3,
    "conf/dcfs/2001": 2,  # DCAGRS 2001, Vienna
}
OTHER_STREAM = "journals/iandc"

HEADER = '<?xml version="1.0" encoding="ISO-8859-1"?>\n<!DOCTYPE dblp SYSTEM "dblp.dtd">\n<dblp>\n'


def main(dump_dir: Path) -> None:
    streams = {stream_of(k) for k in EDITIONS}
    kept: dict[str, list[str]] = {}
    taken: Counter[str] = Counter()
    other = None
    for record in iter_records(
        dump_dir / "dblp.xml.gz",
        dump_dir / "dblp.dtd",
        key_filter=lambda k: stream_of(k) in streams or k.startswith(OTHER_STREAM + "/"),
        keep_xml=True,
    ):
        if record.key.startswith(OTHER_STREAM + "/"):
            if other is None and record.tag == "article":
                other = record.xml
            continue
        if record.tag == "proceedings" and record.key in EDITIONS:
            kept.setdefault(record.key, []).insert(0, record.xml or "")
        elif record.tag == "inproceedings":
            ref = record.first("crossref")
            if ref in EDITIONS and taken[ref] < EDITIONS[ref]:
                taken[ref] += 1
                kept.setdefault(ref, []).append(record.xml or "")
    out = Path(__file__).with_name("dblp_sample.xml.gz")
    with gzip.open(out, "wt", encoding="iso-8859-1", newline="\n") as handle:
        handle.write(HEADER)
        for key in EDITIONS:
            for xml in kept.get(key, []):
                handle.write(xml.strip() + "\n")
        if other:
            handle.write(other.strip() + "\n")
        handle.write("</dblp>\n")
    print(f"wrote {out}: {sum(len(v) for v in kept.values())} edition records, 1 other")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
