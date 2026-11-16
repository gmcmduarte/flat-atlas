"""Build the Semantic Scholar test fixtures from real cached answers (P1-03).

Not run by the tests. Run it once after a real ``harvest s2 --limit 100``:

    uv run python tests/fixtures/s2/make_sample.py

It reads ``data/raw/semanticscholar`` through ``SourceClient.iter_cached`` and the DBLP staging
table, picks a handful of records that exercise the parser (abstract + vector + references; a
vector without abstract and with a null reference list; no vector; a DOI that came back null) and
three title matches (a hit, a hit that must be rejected, a 404), trims long lists, and writes
``batch.json`` and ``matches.json`` next to this file. Nothing is invented; of the 768-float
vectors only the first two records keep theirs, so the files stay small.
"""

from __future__ import annotations

import json
from pathlib import Path

from flatatlas.db import connect
from flatatlas.http import SourceClient
from flatatlas.settings import load_settings
from flatatlas.sources import s2 as s2_src
from flatatlas.sources.openalex import load_papers

HERE = Path(__file__).parent
MAX_REFS = 5
MAX_AUTHORS = 3
KEEP_VECTORS = 2


def trim(item: dict, keep_vector: bool) -> dict:
    item = json.loads(json.dumps(item))
    if item.get("references"):
        item["references"] = item["references"][:MAX_REFS]
    item["authors"] = (item.get("authors") or [])[:MAX_AUTHORS]
    if item.get("embedding") and not keep_vector:
        item["embedding"] = None  # the vector alone is 768 floats; most records go without
    return item


def main() -> None:
    settings = load_settings()
    client = SourceClient("semanticscholar", settings)
    answers = s2_src.read_cached_answers(client)
    con = connect(settings.paths, read_only=True)
    papers = {p.dblp_key: p for p in load_papers(con)}
    con.close()

    items = [(doi, entry[1]) for doi, entry in sorted(answers.by_doi.items())]
    found = [(doi, it) for doi, it in items if it]
    nulls = [doi for doi, it in items if it is None]

    def pick(predicate, taken):
        for doi, it in found:
            if doi not in taken and predicate(it):
                taken.add(doi)
                return doi, it
        raise SystemExit("no record fits the predicate; harvest a bigger sample first")

    taken: set[str] = set()
    chosen = [
        pick(lambda i: i.get("abstract") and i.get("embedding") and i.get("references"), taken),
        pick(
            lambda i: (
                i.get("embedding")
                and not i.get("abstract")
                and i.get("references") is None
                and i.get("tldr")
            ),
            taken,
        ),
        pick(lambda i: not i.get("embedding"), taken),
    ]
    ids, answer = [], []
    for n, (doi, item) in enumerate(chosen):
        ids.append(f"DOI:{doi}")
        answer.append(trim(item, keep_vector=n < KEEP_VECTORS))
    for doi in nulls[:2]:
        ids.append(f"DOI:{doi}")
        answer.append(None)
    (HERE / "batch.json").write_text(
        json.dumps({"fields": s2_src.FIELDS, "ids": ids, "answer": answer}, indent=1) + "\n"
    )

    # Title matches: read the cached answers, keep one accepted, one rejected, one 404.
    matches = []
    for p in sorted(papers.values(), key=lambda p: p.dblp_key):
        params = s2_src.match_params(p)
        resp = client.cached(s2_src.MATCH_PATH, params) if params else None
        if resp is None:
            continue
        cands = s2_src._candidates(resp.data)
        item, score = s2_src.best_title_match(p, cands)
        kind = "hit" if item else ("rejected" if cands else "none")
        if kind in {m["kind"] for m in matches}:
            continue
        matches.append(
            {
                "kind": kind,
                "query_title": " ".join(p.title.split()),
                "dblp_key": p.dblp_key,
                "year": p.year,
                "answer": None
                if resp.data is None
                else {"data": [trim(c, keep_vector=False) for c in cands]},
            }
        )
    (HERE / "matches.json").write_text(json.dumps(matches, indent=1) + "\n")
    print(
        f"batch: {len(ids)} ids, {sum(1 for a in answer if a)} answers; matches: "
        f"{[m['kind'] for m in matches]}"
    )


if __name__ == "__main__":
    main()
