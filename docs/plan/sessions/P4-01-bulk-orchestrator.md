# P4-01 — Bulk loaders and the run orchestrator

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P4-01-bulk-orchestrator` · **Depends on:** Gate G3 passed

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §3 (bulk options), §5 (all)
4. `docs/notes/sources.md`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Make the pipeline efficient and robust at field scale: bulk input where it beats API calls, and a `run` command that survives interruptions.

## Build
- DBLP dump loader: streaming parser for `dblp.xml.gz` with its DTD (lxml iterparse, constant memory), filtered to configured streams, producing the same `stg_dblp_*` tables as the API path. Download with resume and checksum; record the dump date in the manifest.
- OpenAlex at scale: fetch by source ID with cursor paging for journals and by DOI batches for DBLP-defined conference papers; optional snapshot path only if the server disk allows (read Parquet from the public bucket filtered by source IDs with DuckDB `httpfs`; test whether this is practical and record the finding).
- Semantic Scholar at scale: batch endpoint remains the default; evaluate the Datasets API for citations (download one file, filter to corpus IDs, measure) and document when it is worth using.
- `flatatlas run --profile P [--from stage] [--to stage] [--incremental]`: stage graph with per-stage state in `ops_run_log`; resumes at the failed stage; lock file to prevent two runs; summary at the end.
- `flatatlas status`: progress per harvest job with ETA, last run per stage, disk usage per data folder, daily API spend.
- Memory discipline: DuckDB memory limit from the profile; chunked processing in embed and tag.

## Test
- Dump parser equals the API path on the pilot venues (table diff test on a trimmed dump fixture).
- Orchestrator tests: failure in stage k → rerun resumes at k; lock prevents a second run.
- Memory test on the full dump on the server: peak under 4 GB (I run it; you read the log).

## Done when
- Dump path and API path agree on the pilot venues.
- `run` resumes after a forced kill.
- `status` shows progress, ETA, disk and spend.
- Findings on snapshot and Datasets usefulness written to `docs/notes/bulk-findings.md`.

## Long job (Guilherme launches it, not you)
Prove the command works with `--limit 50`. Then give me the exact full command, wrapped as `uv run flatatlas … 2>&1 | tee data/logs/<date>-<name>.log` (on the Mac prefix it with `caffeinate -i`; on the server run it inside tmux). Stop and wait. When I say it finished, read the log tail and `ops_harvest_state`, and continue.

## Out of scope
- Running the full harvest (P4-02).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P4-01, add a dated entry (built, not built, surprises) and a hand-off note for P4-02.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
