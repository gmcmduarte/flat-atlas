# P2-03 — Venue analytics: pipeline

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P2-03-venue-analytics-data` · **Depends on:** P2-01

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §4.5, §15.1
4. `config/venue_facts.yaml`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Every venue metric that can be computed, each with its coverage and source, and no composite score.

## Build
- `aggregate/venues.py` → `agg_venue_year` with, per venue and year (and with/without predecessors): papers; authors per paper (mean, median); distinct authors; returning vs new authors (ever before, and within 5 years); countries and institutions with fractional counting and the share of authorships with known affiliation; citations at 5 years after publication: median and quartiles from `counts_by_year` (only for years at least 5 years old); topic profile at level 0 and level 1 (confidence-weighted shares); open-access share; page length.
- `agg_venue_overlap`: topic-profile cosine and author-set Jaccard between venues, overall and per 5-year window.
- `venue_facts.yaml` loader: CORE/ICORE rank (value, edition, URL) and acceptance figures (submissions, accepted, source URL, note). Validation: a number without a source URL is rejected. Tell Guilherme how to export ranks from the CORE portal by hand (it blocks automated access) and how to add acceptance numbers found in prefaces (Claude chat can extract them from PDFs).
- Coverage columns for every metric (what share of the underlying rows had the needed data).
- Export `venue/<id>.json` and `venues.json` extended with all metrics; update schemas and generated types.

## Test
- A fixture venue of 3 years and about 12 papers with hand-computed expected values for every metric, including returning authors and fractional country counts.
- Test that the 5-year citation metric is null for recent years.

## Done when
- `agg_venue_year` and `agg_venue_overlap` exist for all venues.
- Every metric has a coverage figure.
- No acceptance rate without a source.
- Show me the table for DLT and one journal.

## Out of scope
- UI (P2-04). Any ranking or composite score: forbidden by design.

## At the end
- Run `uv run pytest` and `uv run ruff check .`, and `npm run check`, `npm run test` and `npm run build` in `web/` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P2-03, add a dated entry (built, not built, surprises) and a hand-off note for P2-04.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
