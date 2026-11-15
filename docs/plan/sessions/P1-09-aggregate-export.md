# P1-09 — Aggregates, topic edges, map layout, release, static export

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P1-09-aggregate-export` · **Depends on:** P1-08

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §4.3 (edge table), §4.5, §4.7, §9.4 (volume), §10, §11.2, §11.4 (layout)
4. `web/src/lib/data/types.ts`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Everything the site needs, computed in the pipeline and written as a versioned release and as static JSON.

## Build
- `aggregate/edges.py`: `related` (normalised PMI with minimum support), `builds-on` (directed citation flow vs a size-preserving null model), `shared-community` (author-activity cosine). Never between ancestor/descendant pairs. Weight, confidence, evidence counts, provenance. Stored in `core_topic_edge` with `subtopic-of`.
- `aggregate/topics.py`: `agg_topic_year`, `agg_topic_author`, `agg_topic_venue`; confidence-weighted volume rolled up the DAG without double counting; paper ranking score per topic (confidence × log citations).
- `aggregate/layout.py`: deterministic layout per PLAN §11.4: level-0 by ForceAtlas2 (python: `fa2`-style implementation or igraph/networkx with fixed seed), children packed inside the parent disc with collision; primary parent for multi-parent topics; output `agg_map_layout`.
- `release/build.py`: runs the data-quality and evaluation checks, then writes `releases/v<YYYY.MM.patch>/` with all Parquet files of PLAN §4.7, `manifest.json` (row counts, sha256, versions, source fetch dates), `SOURCES.md`, `LICENSE.md` (CC BY 4.0 text reference), `CITATION.cff`. Asserts that no abstract text and no embedding is included.
- `export/static.py`: release → `web/static/data/` in the layout of PLAN §11.2 (topics.json, topic/<id>.json, works shards, authors shards, venue/<id>.json, map.json, search/index.json built with the MiniSearch-compatible structure or raw documents for the client to index).
- Generate JSON Schemas from the pydantic export models and TypeScript types from them (`web/src/lib/data/types.ts` becomes generated); CI checks they are in sync.

## Test
- Unit tests with hand-computed toy data for each edge type and for the roll-up without double counting.
- Layout determinism test; no overlapping siblings.
- Release test: manifest checksums verify; forbidden columns absent.
- Export test: every JSON file validates against its schema.

## Done when
- Four edge types present and separate.
- A release folder with a valid manifest exists.
- Static export total size reported and under 30 MB.
- Show me the top 10 `related` and `builds-on` edges; they should look sensible to a FLAT researcher.

## Out of scope
- Frontend code beyond the generated types. Venue analytics (P2-03).

## At the end
- Run `uv run pytest` and `uv run ruff check .`, and `npm run check`, `npm run test` and `npm run build` in `web/` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-09, add a dated entry (built, not built, surprises) and a hand-off note for P1-10.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
