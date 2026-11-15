# P6-02 — zbMATH Open source and the MSC signal

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P6-02-zbmath` · **Depends on:** P6-01

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §3 (zbMATH row), §9.3 (`src_msc`), §10 (share-alike rule)
4. `reports/gaps.md`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Add zbMATH Open for older and mathematical literature and use MSC codes as a tagging signal, while keeping share-alike data separate.

## Build
- Verify and record in `docs/notes/sources.md`: current zbMATH Open REST and OAI-PMH endpoints, whether MSC codes and references are in the payload, terms of use, a polite rate.
- `sources/zbmath.py`: harvest by MSC code (the FLAT codes in `taxonomy/seeds/msc.yaml`) and by journal for the fill list; parse to `stg_zbmath_*` (id, title, authors with zbMATH author IDs, year, source, MSC codes, DOI, references if open).
- Matching to existing works (DOI, then title/year/author); new works enter as candidates through the scope rule with an MSC-based signal.
- `src_msc` signal: map MSC codes to topics through `xref.msc`; add to the tagger config; re-evaluate (anchors, agreement) with and without it.
- Licence separation: zbMATH-derived columns only in `zbmath_addon.parquet` (CC BY-SA 4.0); the licence check from P5-06 enforces it; update `/sources`.
- Review the grey area noted in PLAN §10 (tags influenced by MSC) and write the conclusion in DECISIONS; if in doubt, keep `src_msc` out of the published tagger and use it only for evaluation.

## Test
- Parser and matcher tests on fixtures; licence check test with a deliberately leaked column.

## Done when
- zbMATH records matched with confidence; counts of new candidates by decade.
- Evaluation with/without `src_msc` recorded.
- Share-alike data isolated; licence check passes.

## Long job (Guilherme launches it, not you)
Prove the command works with `--limit 50`. Then give me the exact full command, wrapped as `uv run flatatlas … 2>&1 | tee data/logs/<date>-<name>.log` (on the Mac prefix it with `caffeinate -i`; on the server run it inside tmux). Stop and wait. When I say it finished, read the log tail and `ops_harvest_state`, and continue.

## Out of scope
- Backfilling specific venues (P6-03).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P6-02, add a dated entry (built, not built, surprises) and a hand-off note for P6-03.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
