"""Build the OpenAlex and Crossref test fixtures from real cached answers (P1-02).

Not run by the tests. Run it once after a real ``--limit`` harvest:

    uv run python tests/fixtures/openalex/make_sample.py

It reads ``data/raw/openalex`` and ``data/raw/crossref`` through ``SourceClient.iter_cached``,
picks a handful of records that exercise the parser (an abstract, several institutions for one
author, an author without institution, a missing author ID, a title-search hit and a miss),
trims long lists, and writes JSON next to this file and to ``tests/fixtures/crossref/``.
Nothing is invented: every field value comes from the sources.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from flatatlas.http import SourceClient
from flatatlas.settings import load_settings

HERE = Path(__file__).parent
CROSSREF_DIR = HERE.parent / "crossref"
MAX_REFS = 5
MAX_AUTHORS = 4
# Title searches worth keeping: a clean hit, a hit with a near-duplicate title next to it, a miss.
KEEP_SEARCHES = (
    "Geometrical OL-Systems Coming from Tilings of the Plane",
    "State Complexity of Some Operations on Regular Languages",
    "On the Representation of Finite Automata",
)
# Crossref abstracts in JATS: a heading, markup, an entity (real records found with has-abstract).
JATS_DOIS = ("10.1515/comp-2017-0004", "10.46298/dmtcs.9063", "10.1145/3632915")


def trim(work: dict) -> dict:
    work = json.loads(json.dumps(work))
    work["referenced_works"] = (work.get("referenced_works") or [])[:MAX_REFS]
    work["authorships"] = (work.get("authorships") or [])[:MAX_AUTHORS]
    work["topics"] = (work.get("topics") or [])[:2]
    work["keywords"] = (work.get("keywords") or [])[:3]
    work["counts_by_year"] = (work.get("counts_by_year") or [])[:3]
    return work


def main() -> None:
    settings = load_settings()
    client = SourceClient("openalex", settings)
    works: dict[str, dict] = {}
    searches: list[tuple[dict, dict]] = []
    for resp in client.iter_cached("/works"):
        if resp.status != 200 or not isinstance(resp.data, dict):
            continue
        query = parse_qs(urlparse(resp.url).query)
        if "abstract_inverted_index" not in (query.get("select") or [""])[0]:
            continue  # an older probe that asked for fewer fields
        flt = (query.get("filter") or [""])[0]
        for work in resp.data.get("results") or []:
            works.setdefault(work["id"], work)
        if flt.startswith("title.search:"):
            searches.append((query, resp.data))

    def pick(predicate, taken: set[str]):
        for wid, work in sorted(works.items()):
            if wid not in taken and "abstract_inverted_index" in work and predicate(work):
                taken.add(wid)
                return work
        raise SystemExit("no work fits the predicate; harvest a bigger sample first")

    taken: set[str] = set()
    chosen = [
        pick(lambda w: w.get("abstract_inverted_index") and len(w["authorships"]) >= 2, taken),
        pick(lambda w: any(len(a.get("institutions") or []) >= 2 for a in w["authorships"]), taken),
        pick(lambda w: not any(a.get("institutions") for a in w["authorships"]), taken),
        pick(lambda w: any(not (a.get("author") or {}).get("id") for a in w["authorships"]), taken),
        pick(
            lambda w: not w.get("referenced_works") and not w.get("abstract_inverted_index"), taken
        ),
    ]
    (HERE / "works.json").write_text(
        json.dumps([trim(w) for w in chosen], indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("works.json:", [w["id"] for w in chosen])

    # Title searches: a hit and a miss, with the request's title and year recovered from the URL.
    out = []
    for query, data in searches:
        flt = query["filter"][0]
        title = flt.split(",publication_year:")[0].removeprefix("title.search:")
        years = flt.split("publication_year:")[1].split("|")
        if title in KEEP_SEARCHES:
            out.append(
                {
                    "query_title": title,
                    "years": years,
                    "results": [trim(w) for w in data["results"]],
                }
            )
    (HERE / "title_searches.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("title_searches.json:", len(out), "searches")

    # Crossref: the real single-DOI answers already cached for pilot DOIs.
    cr = SourceClient("crossref", settings)
    records = []
    for resp in cr.iter_cached("/works/10."):
        msg = (resp.data or {}).get("message") if isinstance(resp.data, dict) else None
        if msg and len(records) < 4:
            msg = json.loads(json.dumps(msg))
            msg["reference"] = (msg.get("reference") or [])[:MAX_REFS]
            msg["author"] = (msg.get("author") or [])[:2]
            for key in ("link", "license", "assertion", "relation", "content-domain", "resource"):
                msg.pop(key, None)
            records.append(msg)
    jats = {}
    for resp in cr.iter_cached("/works"):
        items = (
            ((resp.data or {}).get("message") or {}).get("items")
            if isinstance(resp.data, dict)
            else None
        )
        for item in items or []:
            if item.get("DOI") in JATS_DOIS and item.get("abstract"):
                jats[item["DOI"]] = item["abstract"]
    (CROSSREF_DIR / "jats_abstracts.json").write_text(
        json.dumps(jats, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("jats abstracts:", sorted(jats))
    (CROSSREF_DIR / "works.json").write_text(
        json.dumps(records, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("crossref works.json:", [r["DOI"] for r in records])


if __name__ == "__main__":
    main()
