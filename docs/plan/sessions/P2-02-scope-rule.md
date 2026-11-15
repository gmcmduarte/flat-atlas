# P2-02 — Scope rule for broad venues (Opus)

**Tool:** Claude Code · **Model:** **Opus** · **Branch:** `s/P2-02-scope-rule` · **Depends on:** P2-01

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §6 (all), §7.2, §4.2 (`core_stub`, scope columns)
4. `docs/plan/RISKS.md` R9
5. `config/tagger.yaml`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Implement and tune the inclusion rule so that broad venues contribute only papers that come from automata and formal languages, with a score and a reason for every decision.

## Build
- `scope/signals.py` and `scope/decide.py` implementing PLAN §6: lexical, source-topic whitelist (learned from what Tier A works receive, with a lift threshold), citation share (needs stubs: harvest metadata for frequently referenced non-corpus works from `stg_reference_candidates`), embedding kNN vote against a background sample, community signal. Noisy-or fusion, the 'no single weak signal' rule, statuses `core/in/borderline/stub/out`, `scope_reason` text.
- `config/scope.yaml`: weights, thresholds, and the four field guards (verification, combinatorics, natural computing, grammatical inference) as phrase/condition lists. Use your FLAT judgment for the guards and write the reasoning in `docs/notes/scope-design.md`.
- Automatic tuning harness: (1) hold out 20 % of Tier A works and treat them as unknown: recall; (2) background sample of non-theory CS and of non-word combinatorics: false-positive rate; (3) per-signal ablation. No hand labels.
- Trial: harvest two broad venues as candidates (MFCS and Information and Computation, including Information and Control) and apply the rule. Report counts per status per decade and 40 borderline + 20 random `in` + 20 random `out` examples in `reports/scope-trial.html`.
- Stop for Guilherme's 20-minute read of the report; adjust guards from his comments; record final thresholds.
- Tier C expansion is designed (round limit, thresholds) but only run on a small sample here.

## Test
- Unit tests for each signal and guard, including classic traps: 'model checking' alone (out), 'timed automata' (in), 'card shuffling' (out), 'Sturmian words' (in), 'genetic algorithm' (out), 'P systems' (in).

## Done when
- Hold-out recall ≥ 90 %; background false-positive rate ≤ 5 %.
- Every candidate work has status, score and reason.
- Guilherme has read the trial report; thresholds are in `config/scope.yaml` and DECISIONS.
- Out-of-scope candidates are not on the site; `in` works are tagged and exported.

## Long job (Guilherme launches it, not you)
Prove the command works with `--limit 50`. Then give me the exact full command, wrapped as `uv run flatatlas … 2>&1 | tee data/logs/<date>-<name>.log` (on the Mac prefix it with `caffeinate -i`; on the server run it inside tmux). Stop and wait. When I say it finished, read the log tail and `ops_harvest_state`, and continue.

## Out of scope
- Harvesting all broad venues (P4-02). Changing the tagger.

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P2-02, add a dated entry (built, not built, surprises) and a hand-off note for P2-03 (Sonnet).
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
