# P5-04 — Chair tools: reviewer suggestions and conflicts of interest

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P5-04-chair-tools` · **Depends on:** P5-03

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §15.5, §8.3 (confidence rules)
4. `docs/plan/RISKS.md` R5 and R12

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Help PC chairs find people by topic expertise and recent activity, and spot co-authorship conflicts, with the evidence shown and the limits stated.

## Build
- Pipeline: per author topic-expertise vectors with recency decay (half-life in config), last-active year, first-paper year, last known affiliation with its year; `agg_author_coauthor` by year.
- API: `/api/reviewers?topics=&active_since=&min_papers=&exclude=` and `/api/coi?authors=&candidates=&window=`; only authors with `resolution_confidence ≥ 0.8`; pagination; stricter rate limit.
- UI `/chairs`: (1) pick topics → ranked people with the papers that justify each, filters, export CSV; (2) paste two name lists (PC and authors) → resolve names to Atlas authors with a disambiguation step → COI matrix with evidence (paper, year) and a window control (default 5 years); same-institution flag with the year of the affiliation.
- A clear notice: suggestions only, name ambiguity, missing affiliations, no ranking of people's quality. No stored input: lists stay in the browser/session.
- Static mode: hide the tool or run it in the browser if the data is small enough; decide and record.

## Test
- Unit tests for scoring with decay, for the COI window edges, and for name resolution (homonyms must ask, not guess).
- API tests; Playwright for both flows.

## Done when
- Reviewer list for a topic set with evidence and CSV export.
- COI matrix correct on a fixture with known co-authorships.
- Low-confidence authors never appear.
- Notice visible; nothing a user pastes is stored or logged.

## Out of scope
- Paper-to-reviewer assignment, bidding, any account system.

## At the end
- Run `uv run pytest` and `uv run ruff check .`, and `npm run check`, `npm run test` and `npm run build` in `web/` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P5-04, add a dated entry (built, not built, surprises) and a hand-off note for P5-05.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
