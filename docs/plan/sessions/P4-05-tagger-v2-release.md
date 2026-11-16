# P4-05 — Tagger v2 on the full field, distilled classifier, incremental mode, release 1.0 (Opus)

**Tool:** Claude Code · **Model:** **Opus** · **Branch:** `s/P4-05-tagger-v2-release` · **Depends on:** P4-04

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §9 intro, §9.4, §9.5, §9.6, §9.7, §9.8, §5.3
4. `docs/plan/DECISIONS.md` D-61 to D-67 and the decision of P1-08 that names the adopted method
5. `config/tagger.yaml`
6. `docs/notes/tagger-experiments.md`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
The best free tagger we can justify on the full field, a small distilled classifier so that weekly papers never need the large model, incremental tagging, and the first full public release.

## Cost
€0. Local models on the server and the Mac, free API tiers, cached data. Check whether D-67 has been approved since it was drafted: **if it is still "not active", no hosted model is used or compared in this session.** If it was approved, follow its conditions to the letter (cap enforced in code, pinned version, no abstracts or TLDRs sent) and treat the hosted run as a comparison on the held-out third first.

## Build
- **Retrain on the full field.** Rebuild artefacts for taxonomy v2; silver labels with the leak rule; fusion model on gold-train (as migrated and extended in P4-04) + silver; isotonic calibration; shortlist recall re-measured. Tune on gold-train only.
- **Decision model at scale** (only if P1-08 kept it): measure the share of unsure works on the full corpus and the works per minute on the server; give me the projected hours. If the projection is more than about 10 nights, propose a cut (narrower band, fewer option orders, smaller model) and show its effect on gold-train. The run is resumable and cached; I launch it.
- **Distilled classifier** (cascade step 4, PLAN §9.7): train GLiClass and SetFit (check weights and licences first; record them) on the decision model's answers + gold-train to predict level-0 and level-1 topics from the composite text; keep the better on gold-train cross-validation; wire it in as the `distil` signal for works that have no `dm_*`.
- **Comparison on the held-out third, opened once after all tuning:** the P1-08 method re-trained on the full field; with and without the decision model; the incremental path (`distil` in place of `dm_*`). Same table and adoption rule as PLAN §9.6. Record the table whatever the outcome; adopt the distilled path for increments only if it stays within the noise of the full cascade.
- `tag --incremental`: frozen artefacts and models per `tagger_version`; tag only new or changed works, using `distil` and never loading the large model; monthly artefact refresh job; full re-tag on version bump.
- Wire the weekly incremental run and the monthly release into the timers from P3-05; failure summary in `flatatlas status`.
- Full run: tag → decide (long job) → tag (final fusion) → evaluate → aggregate → release `v1.0.0` → load → activate (I launch; you verify).
- Check site and API at full size: slowest endpoints, map payload size, search latency; fix what misses the budgets (indexes, pagination, payload trimming).

## Test
- Unit tests for silver-label construction and the leak rule; the held-out guard; incremental equals full on a fixture (same tags for unchanged works); the incremental path never imports the decision-model runtime.
- Evaluation on the full corpus.

## Done when
- The comparison table is recorded; the adopted tagger meets all PLAN §9.6 thresholds on the full corpus, including the held-out floor set at gate G1.
- 1,000 new works tagged incrementally in under 5 minutes without the large model.
- The weekly timer ran end to end once.
- Release `v1.0.0` is live on the server.
- The session's spend is €0 (or, if D-67 was approved, the spend log shows the amount and that the cap held).

## Long job (Guilherme launches it, not you)
Prove the command works with `--limit 50`. Then give me the exact full command, wrapped as `uv run flatatlas … 2>&1 | tee data/logs/<date>-<name>.log` (on the Mac prefix it with `caffeinate -i`; on the server run it inside tmux). Stop and wait. When I say it finished, read the log tail and `ops_harvest_state`, and continue.

## Out of scope
- New features (Phase 5). Hierarchical encoder heads and other models that need thousands of labels (parking lot). Any service with a running cost.

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P4-05, add a dated entry (built, not built, surprises) and a hand-off note for the G4 gate review (Opus, `GATE.md`).
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
