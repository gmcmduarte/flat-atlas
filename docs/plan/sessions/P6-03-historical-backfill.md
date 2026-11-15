# P6-03 — Historical backfill

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P6-03-historical-backfill` · **Depends on:** P6-02

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §7.2 (historical), §8
4. `reports/gaps.md`
5. `docs/notes/venues-full.md`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Fill the ranked gaps: old venues and the most-cited missing works, then measure the improvement.

## Build
- Add the historical venues from the fill list to `config/venues.yaml` (SWAT/FOCS early years, Information and Control, Mathematical Systems Theory, EIK, and the others the report ranks high), each with the source that defines membership and verified years.
- Promote frequently cited missing works with an external ID to full records (harvest by ID); run the scope rule on them.
- For unresolved reference strings cited ≥ N times: try Crossref bibliographic search (rate-limited, cached) and zbMATH search; accept only high-score matches; list the rest for community suggestions.
- Older records: handle missing DOIs, initials-only author names, transliteration variants and non-English titles in normalisation and author matching, with tests; keep such authors provisional unless well supported.
- Re-run the pipeline; taxonomy proposals for historical topics to `taxonomy/proposals/` with a short review note.
- Re-run the gap analysis and add a before/after table to `reports/gaps.md`.

## Test
- Tests for the new normalisation cases and the reference-string matcher (precision on a fixture).
- Data-quality and evaluation checks on the full run.

## Done when
- Pre-1990 coverage improved, with the before/after table.
- All pre-1990 anchors present and correctly tagged.
- No drop in evaluation thresholds.

## Long job (Guilherme launches it, not you)
Prove the command works with `--limit 50`. Then give me the exact full command, wrapped as `uv run flatatlas … 2>&1 | tee data/logs/<date>-<name>.log` (on the Mac prefix it with `caffeinate -i`; on the server run it inside tmux). Stop and wait. When I say it finished, read the log tail and `ops_harvest_state`, and continue.

## Out of scope
- Digitising sources that are not open; manual data entry.

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P6-03, add a dated entry (built, not built, surprises) and a hand-off note for the G6 gate review (Opus, `GATE.md`).
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
