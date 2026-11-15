# P5-03 — Student reading paths

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P5-03-reading-paths` · **Depends on:** P5-02

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §15.4, §4.2 (`is_survey`)

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Per topic, a short ordered reading list: foundations, surveys, core, frontier, each with the reason.

## Build
- Survey detection: title cues, work type, reference count relative to venue norm, handbook and survey-journal venues, 'invited' markers; a score and `survey_confidence`; rules in config.
- `agg_reading_path` per PLAN §15.4: steps Foundations, Surveys, Core, Frontier; 5–8 works per step; a reason string for each choice; in-topic citation counts from `core_citation` restricted to works tagged with the topic or its descendants.
- UI: a 'Start here' tab on topic pages with the four steps; open-access links highlighted; a note on how the list is produced.
- Topics with fewer than 30 works inherit the parent's path with a notice.

## Test
- Unit tests for survey rules (including false friends such as 'A survey-free approach') and for step selection on toy data.
- Write a 50-item sample of detected surveys to `reports/` for the gate to judge.

## Done when
- Every topic with ≥ 30 works has a four-step path with reasons.
- Survey sample produced for the gate (target precision ≥ 80 %).
- Pages render in both data-source modes.

## Out of scope
- Personalised recommendations.

## At the end
- Run `uv run pytest` and `uv run ruff check .`, and `npm run check`, `npm run test` and `npm run build` in `web/` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P5-03, add a dated entry (built, not built, surprises) and a hand-off note for P5-04.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
