# P4-05 — Tagger v2, incremental mode, scheduled refresh, release 1.0 (Fable)

**Tool:** Claude Code · **Model:** **Fable** · **Branch:** `s/P4-05-tagger-v2-release` · **Depends on:** P4-04

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §9.4 (v2), §9.5, §9.6, §9.7, §5.3
4. `config/tagger.yaml`
5. `docs/notes/tagger-experiments.md`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
The best free tagger we can justify on the full field, incremental tagging for new papers, and the first full public release.

## Build
- Weak supervision per PLAN §9.4: build silver positives and negatives; pair-feature logistic regression with the leak-avoidance rule (do not use as a feature the signal that defined the label); isotonic calibration; compare with v1 on anchors, coverage, coherence, agreement, citation consistency, stability. Adopt v2 only if it wins clearly; record the table either way.
- Decide with evidence whether the optional local LLM signal is worth enabling for the low-confidence band (run it on a 500-work sample if Ollama is available on the server; measure anchor and agreement effect and hours needed). Default stays off.
- `tag --incremental`: frozen artefacts per `tagger_version`; tag only new or changed works; monthly artefact refresh job; full re-tag on version bump.
- Wire the weekly incremental run and the monthly release into the timers from P3-05; failure summary in `flatatlas status`.
- Full run: tag → evaluate → aggregate → release `v1.0.0` → load → activate (I launch; you verify).
- Check site and API at full size: slowest endpoints, map payload size, search latency; fix what misses the budgets (indexes, pagination, payload trimming).

## Test
- Unit tests for silver-label construction and the leak rule; incremental equals full on a fixture (same tags for unchanged works).
- Evaluation on the full corpus.

## Done when
- v1 vs v2 comparison recorded; the adopted tagger meets all PLAN §9.6 thresholds on the full corpus.
- 1,000 new works tagged incrementally in under 5 minutes.
- The weekly timer ran end to end once.
- Release `v1.0.0` is live on the server.

## Long job (Guilherme launches it, not you)
Prove the command works with `--limit 50`. Then give me the exact full command, wrapped as `uv run flatatlas … 2>&1 | tee data/logs/<date>-<name>.log` (on the Mac prefix it with `caffeinate -i`; on the server run it inside tmux). Stop and wait. When I say it finished, read the log tail and `ops_harvest_state`, and continue.

## Out of scope
- New features (Phase 5).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P4-05, add a dated entry (built, not built, surprises) and a hand-off note for the G4 gate review (Fable, `GATE.md`).
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
