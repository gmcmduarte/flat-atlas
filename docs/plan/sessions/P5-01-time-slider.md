# P5-01 — Time slider

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P5-01-time-slider` · **Depends on:** Gate G4 passed (or G1 for the static variant)

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §15.2, §11.4
4. `web/src/lib/map/` (all files)

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Watch the map evolve from the 1950s to today.

## Build
- Pipeline: per topic and year, cumulative and 5-year-window volumes; first-active year (≥ 3 works); add compact per-year arrays to the map payload (static `map.json` and `/api/map`).
- UI: a slider with year label, play/pause, speed; a switch 'cumulative' vs 'active in the last 5 years'; positions fixed, sizes and opacity animate; topics not yet born are hidden; edges recomputed per window only if cheap, otherwise hidden while playing.
- Topic pages: the sparkline marks the slider's year when arriving from the map.

## Test
- Unit tests for the yearly aggregates (toy data) and the size interpolation.
- Playwright: move the slider to 1975 and to today; bubble count and one known topic's presence differ as expected.

## Done when
- Slider and play work smoothly on the M1.
- Positions do not move over time.
- Payload growth for the map reported and acceptable (under 1 MB gzip).

## Out of scope
- Per-year layouts. New metrics.

## At the end
- Run `uv run pytest` and `uv run ruff check .`, and `npm run check`, `npm run test` and `npm run build` in `web/` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P5-01, add a dated entry (built, not built, surprises) and a hand-off note for P5-02.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
