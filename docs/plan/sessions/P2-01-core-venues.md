# P2-01 — Remaining core venues by configuration

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P2-01-core-venues` · **Depends on:** Gate G1 passed

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §7 (all), §8.4
4. `docs/plan/reviews/G1-review.md` (fix list)
5. `docs/notes/venues-pilot.md`
6. `docs/plan/OPEN-QUESTIONS.md` (answers on venue tiers)

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Prove that adding venues is a config change: bring in the rest of the core list and re-run the whole pipeline.

## Build
- Add to `config/venues.yaml`, each verified against DBLP and OpenAlex and noted in `docs/notes/venues-core.md`: NCMA, AFL, LATA, WORDS, CAI, MCU, RP, UCNC (with UC, UMC), JALC (with EIK if indexed), IJFCS, RAIRO-ITA, plus the Tier A additions Guilherme approved (ICGI, CMC, Journal of Membrane Computing, AUTOMATA, and so on). Journals marked Tier B wait for P2-02.
- EPTCS-published proceedings (NCMA, AFL) and journals: check how DBLP lists them (journal volumes vs conference streams) and extend the venue model only if needed, with tests.
- Run harvest → parse → resolve → embed → tag → evaluate → aggregate → release → export. Any code change must be a bug fix or a general capability, never a venue-specific branch.
- Now that journals are present, check conference→journal merging on real pairs; tune `config/resolve.yaml`; update the merge report.
- `taxonomy propose` on the larger corpus: write proposals for new areas to `taxonomy/proposals/v1.1.yaml` and a short review note for Guilherme (20–30 minutes of his time). Apply only what he approves.
- Update `expected_topics` for venues with an obvious profile (WORDS, RP, MCU, UCNC, CMC, ICGI).
- Remove the 'three venues' banner text; show the venue count instead.

## Test
- Tests for every bug fixed. Data-quality checks and evaluation thresholds on the full run.

## Done when
- All listed venues are in the Atlas with verified histories.
- `git diff --stat` shows no venue-specific code.
- Evaluation thresholds still met; merge report read by Guilherme.
- Disk use of `data/` reported (stop and tell me if above 12 GB).
- Site redeployed with the new release.

## Long job (Guilherme launches it, not you)
Prove the command works with `--limit 50`. Then give me the exact full command, wrapped as `uv run flatatlas … 2>&1 | tee data/logs/<date>-<name>.log` (on the Mac prefix it with `caffeinate -i`; on the server run it inside tmux). Stop and wait. When I say it finished, read the log tail and `ops_harvest_state`, and continue.

## Out of scope
- Broad venues and the scope rule (P2-02).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P2-01, add a dated entry (built, not built, surprises) and a hand-off note for P2-02 (Opus).
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
