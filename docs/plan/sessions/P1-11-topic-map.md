# P1-11 — Site: topic map with semantic zoom

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P1-11-topic-map` · **Depends on:** P1-10

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §11.4
4. `web/static/data/map.json` (structure only: read the first 60 lines)
5. `web/src/lib/data/types.ts`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
The map on the home page: bubbles sized by research volume, expanding in place, never a hairball.

## Build
- `TopicMap.svelte` with Sigma.js v3 + graphology, using the precomputed positions (no layout in the browser except short collision relaxation when expanding).
- Initial view: level-0 bubbles (15–25), size = volume (square-root scale), colour by level-0 topic, labels always visible at this level.
- Expand in place on click or zoom threshold: children appear inside the parent hull with a short animation; siblings stay; collapse on zoom out or on a 'back' control. Cap about 150 drawn nodes; deeper levels replace shallower ones as you zoom.
- Edges aggregated to the visible level; only the strongest k per node; a toggle to choose one edge type (`related` default, `builds-on` drawn with direction, `shared-community`), each with its own style and a legend.
- Hover: tooltip with name, volume, top authors. Click on a label or double click: go to the topic page. Search box can focus the map on a topic. URL keeps the map state (expanded topic).
- List view alternative (tree list with the same data) and keyboard navigation between bubbles.
- Keep all Sigma-specific code inside `src/lib/map/`.

## Test
- Unit tests for the pure logic (visible-node selection, edge aggregation, top-k).
- Playwright: home shows the expected number of bubbles; clicking one shows its children; toggle changes edges; no console errors.
- Measure frame rate while panning in the browser preview.

## Done when
- 15–25 top-level bubbles; expansion works in place; never more than about 150 nodes drawn.
- Edge-type toggle and legend work; edge types are never mixed without distinction.
- Smooth pan/zoom on the M1; no console errors; list view works.
- Screenshots of three zoom levels attached to the PR.

## Out of scope
- Time slider (P5-01). Changing the layout algorithm in the pipeline (note issues for a follow-up).

## At the end
- Run `npm run check`, `npm run test` and `npm run build` in `web/` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-11, add a dated entry (built, not built, surprises) and a hand-off note for P1-12.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
