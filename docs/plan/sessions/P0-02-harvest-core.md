# P0-02 — Harvest core: settings, HTTP client, storage helpers

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P0-02-harvest-core` · **Depends on:** P0-01

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §3 (limits per source), §4.6, §5.1, §5.4

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
The one module through which all network access goes: cached, rate-limited, retried, resumable and budget-aware. Plus settings/profiles and DuckDB helpers.

## Build
- `settings.py`: pydantic-settings; reads `.env` and `config/profiles/<profile>.yaml`; exposes data root paths (`raw/`, `warehouse/`, `releases/`, `reports/`, `logs/`). Write `config/profiles/pilot.yaml` and `server.yaml` and `config/sources.yaml` (per source: base URL, requests per second, burst, batch size, daily budget, auth style) with the values from PLAN §3; use conservative values where PLAN says unverified.
- `http.py`: `SourceClient(source_name)` on httpx with: disk cache (key = hash of method, URL, sorted params, body; value = gzip JSON + metadata file); token-bucket rate limit; retry with exponential back-off on 429/5xx honouring `Retry-After` and `x-rate-limit-*`; `User-Agent` with project name and contact email; `mailto` for Crossref; keys from settings, redacted in all logs and errors; `refresh_older_than` option.
- Budget guard: per source and UTC day, count estimated cost (cost table in `sources.yaml`: OpenAlex list call $0.0001, singleton $0, search $0.001); raise `BudgetExhausted` cleanly before exceeding the daily budget.
- `paged(job_key, fetch_page)` helper: stores the cursor after each page in `ops_harvest_state`; resumes on restart; marks done.
- `db.py`: open the DuckDB warehouse; helpers to write/replace a table as Parquet atomically (write temp, rename); `ops_run_log` context manager recording stage, timings, counts, status.
- `flatatlas status`: prints harvest states and the last runs.
- Structured logging to stderr and to `data/logs/` with progress every N items and an ETA.

## Test
- All tests offline with pytest-httpx: cache hit makes zero requests; 429 with `Retry-After: 2` waits and retries (mock the clock); a paged job killed after page 3 resumes at page 4; budget guard stops at the limit and resumes next UTC day (mock date); the API key never appears in captured logs or exception text; atomic table write leaves the old table intact on failure.

## Done when
- All tests above pass.
- No module other than `http.py` imports httpx (add a test that greps for it).
- `uv run flatatlas status` runs on an empty data root without error.

## Out of scope
- Real source clients (next sessions). Do not call any real API in tests.

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P0-02, add a dated entry (built, not built, surprises) and a hand-off note for P0-03.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
