# P2-04 — Venue analytics: UI

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P2-04-venue-analytics-ui` · **Depends on:** P2-03

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §15.1 (UI paragraph), §11.3
4. `web/src/lib/data/types.ts` (venue types)

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Venue pages and a compare view for chairs and for researchers choosing where to submit: transparent, side by side.

## Build
- `/venue/[id]`: header with rank (edition and link), years active, predecessors toggle; small-multiple charts over time for each metric (Observable Plot or the chart library already in use); topic profile as a stacked area or ranked bars; top institutions and countries; a facts table with sources as links; coverage notes next to each chart.
- `/venues`: choose 2–5 venues; aligned charts with shared axes; a comparison table (latest 5-year window) with CSV download; topic-overlap and author-overlap matrices shown separately.
- Wording: neutral labels, no 'better/worse' colours, a short 'how to read this' note; unknown values shown as 'not available', never as zero.
- Suggest-a-change link for venue facts (acceptance rates with source).

## Test
- Component tests for the comparison table (null handling, CSV content).
- Playwright: compare three venues; download CSV; toggle predecessors.
- Check charts at mobile width in the browser preview.

## Done when
- All metrics of PLAN §15.1 are visible for a venue, each with source or coverage.
- Compare works for 2–5 venues; CSV downloads.
- No composite score or ranking anywhere.
- No console errors; accessible chart descriptions present.

## Out of scope
- New metrics. Server work.

## At the end
- Run `npm run check`, `npm run test` and `npm run build` in `web/` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P2-04, add a dated entry (built, not built, surprises) and a hand-off note for the G2 gate review (Opus, `GATE.md`).
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
