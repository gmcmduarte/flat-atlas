# P5-02 — Bridge papers

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P5-02-bridge-papers` · **Depends on:** P5-01

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §15.3, §4.5

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
For any two topics, the papers that connect them: the engine of sideways travel.

## Build
- Pipeline: `agg_bridge` per PLAN §15.3 for all topic pairs with a lateral edge: score, the reason (`tagged in both` / `in A, cites into B` / `in B, cites into A`) and the evidence numbers.
- API: `/api/bridge?a=&b=` computing on demand for pairs not precomputed; static export: top 20 per precomputed pair.
- UI: on a topic page, each related/builds-on neighbour has a 'bridge papers' expander; a dedicated `/bridge?a=&b=` page with two topic pickers; clicking an edge on the map opens it.
- Rank by score × log(1 + citations); show the reason per paper.

## Test
- Unit tests on a toy corpus where the right bridge papers are known.
- Playwright: open a topic → bridge to a neighbour → list is non-empty with reasons.

## Done when
- Bridge lists exist for all lateral edges.
- The pair 'shuffle of words' ↔ 'synchronization' (or the reviewed names) returns papers Guilherme finds sensible.
- Ancestor/descendant pairs are rejected with a helpful message.

## Out of scope
- Path-finding across more than two topics.

## At the end
- Run `uv run pytest` and `uv run ruff check .`, and `npm run check`, `npm run test` and `npm run build` in `web/` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P5-02, add a dated entry (built, not built, surprises) and a hand-off note for P5-03.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
