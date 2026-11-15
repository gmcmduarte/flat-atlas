# P4-02 — Full harvest, stubs and scope expansion

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P4-02-full-harvest` · **Depends on:** P4-01

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §6, §7 (all)
4. `config/venues.yaml`
5. `config/scope.yaml`
6. `docs/notes/scope-design.md`
7. `docs/notes/bulk-findings.md`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
The whole field harvested: all Tier A and Tier B venues, stubs, and two controlled expansion rounds.

## Build
- Complete `config/venues.yaml` with every Tier A and Tier B venue agreed at gate G2 (verify each against DBLP/OpenAlex; notes in `docs/notes/venues-full.md`). Venues not in DBLP (some mathematics journals): OpenAlex source ID as the membership definition; extend the venue model with tests.
- A harvest plan in `docs/runbooks/full-harvest.md`: order, expected calls and days per source given the limits, checkpoints, what to do on sustained 429s. I launch each step on the server; you check logs between steps.
- Stub collection: metadata for non-corpus works referenced ≥ k times by in-scope works or citing ≥ k of them (k from config).
- Run `scope` on all candidates; then Tier C expansion round 1 and round 2 with the limits of PLAN §6; stop if a round adds more than a configured share of new works (drift alarm).
- `reports/scope-full.md`: counts per venue, tier, status and decade; top Tier C sources; borderline sample; the hold-out and background tests re-run at scale.
- Record raw-cache size, API spend and elapsed time per source.

## Test
- Re-run unit tests and the scope tuning harness on the full data.
- Data-quality checks after `resolve` on the full corpus.

## Done when
- All configured venues harvested and parsed; failures listed with reasons.
- Scope statuses for all candidates; drift alarm not triggered, or explained.
- No source rate-limited us persistently.
- The scope report is ready for the gate.

## Long job (Guilherme launches it, not you)
Prove the command works with `--limit 50`. Then give me the exact full command, wrapped as `uv run flatatlas … 2>&1 | tee data/logs/<date>-<name>.log` (on the Mac prefix it with `caffeinate -i`; on the server run it inside tmux). Stop and wait. When I say it finished, read the log tail and `ops_harvest_state`, and continue.

## Out of scope
- Author resolution quality (P4-03). Taxonomy changes (P4-04).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P4-02, add a dated entry (built, not built, surprises) and a hand-off note for P4-03 (Opus).
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
