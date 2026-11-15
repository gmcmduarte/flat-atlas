# Progress

## Current state (keep this section under 30 lines)
- **Phase:** 0 (in progress)
- **Last merged session:** P0-01 (PR #1)
- **Next:** review and merge the P0-02 PR, finish `sessions/P0-00-manual-setup.md` (Guilherme), then `P0-03`
- **Live site:** none yet
- **Latest release:** none
- **Known problems:** none
- **Waiting on Guilherme:** the rest of P0-00 (branch protection, secret scanning, Pages source, tmux, pre-commit install; `.env` with the OpenAlex key and contact email now exists; S2 key still empty); review of the P0-02 PR

## Checklist
**Phase 0** — [ ] P0-00 · [x] P0-01 · [x] P0-02 · [ ] P0-03 · [ ] P0-04
**Phase 1** — [ ] P1-01 · [ ] P1-02 · [ ] P1-03 · [ ] P1-04 · [ ] P1-05 · [ ] P1-06 · [ ] P1-07 · [ ] P1-08 · [ ] P1-09 · [ ] P1-10 · [ ] P1-11 · [ ] P1-12 · [ ] G1
**Phase 2** — [ ] P2-01 · [ ] P2-02 · [ ] P2-03 · [ ] P2-04 · [ ] G2
**Phase 3** — [ ] P3-00 · [ ] P3-01 · [ ] P3-02 · [ ] P3-03 · [ ] P3-04 · [ ] P3-05 · [ ] G3
**Phase 4** — [ ] P4-01 · [ ] P4-02 · [ ] P4-03 · [ ] P4-04 · [ ] P4-05 · [ ] G4
**Phase 5** — [ ] P5-01 · [ ] P5-02 · [ ] P5-03 · [ ] P5-04 · [ ] P5-05 · [ ] P5-06 · [ ] G5
**Phase 6** — [ ] P6-01 · [ ] P6-02 · [ ] P6-03 · [ ] G6

## Log (newest first)

### 2026-11-15 — P0-02 Harvest core (branch `s/P0-02-harvest-core`)
- **Built:** `settings.py` (`.env` + profile + `config/sources.yaml`, data-root paths), `http.py` (`SourceClient`: gzip-JSON disk cache, token bucket, retry/back-off with `Retry-After`, budget guard, keys kept out of logs, errors and cache), `budget.py` (daily ledger), `harvest.py` (`paged()` with resume), `db.py` (DuckDB connection, `ops_*` tables, atomic Parquet writes, `run_log`), `log.py` (redacting logging to stderr and `data/logs/`, `Progress` with ETA), `status.py` and the `flatatlas status` command. Config: `config/sources.yaml`, `config/profiles/pilot.yaml`, `server.yaml`. 44 offline tests (all of the prompt's list, plus a mutation check that the key test fails if httpx logs the URL). Decisions D-39 to D-45.
- **Not built:** real source clients (DBLP, OpenAlex, S2, Crossref: P0-03 onwards); async or concurrent fetching; DuckDB views over the Parquet files. `Progress` (logging with ETA) is built and tested but no stage uses it yet.
- **Surprises:** Before the session `.env.example` (tracked) had been filled with real values; nothing had been committed, so it was restored to empty placeholders and the values live in the git-ignored `.env`. gitleaks flagged the fake keys in the tests (marked `# gitleaks:allow`). DuckDB refuses a read-only second connection even inside one process (`ConnectionException`), so `status` handles both that and the cross-process `IOException`. `tenacity` and `rapidfuzz` were already dependencies from P0-01; `tenacity` is unused.
- **Hand-off to P0-03:**
  - Get a client with `SourceClient("dblp", load_settings())`; use `.get(path, params, cost=...)` and read `.data`. Use `cost="singleton"` for OpenAlex lookups by ID or DOI (free) and the default `"list"` for filter calls. In tests use the `settings` fixture (real config, temp data root, fake keys) and `httpx_mock`; `FakeClock` in `tests/helpers.py` avoids real sleeping.
  - `SourceClient.request` returns `Response(status, data, fetched_at, from_cache, url)`; `data` is None for a cached 404/410.
  - Fixtures for P0-03 must come from real DBLP responses: run `flatatlas`-side code once with real network, then trim the cached gz JSON from `data/raw/dblp/`.
  - Open the warehouse with `db.connect(settings.paths)`; wrap stages in `db.run_log(con, "stage")`; page through cursors with `harvest.paged(...)`. A long job holds the DuckDB write lock, so `flatatlas status` reports "locked" while one runs.
  - Verify in the first live session: the OpenAlex key parameter (`api_key`), DBLP rate behaviour, S2 batch size. Record results in `docs/notes/sources.md`.

### 2026-11-15 — P0-01 Project scaffold, tooling and CI (branch `s/P0-01-scaffold`)
- **Built:** `pyproject.toml` (uv, Python pinned to 3.12 in `.python-version`, `uv.lock` committed), package `src/flatatlas/` with the Typer CLI (`--version` and 13 empty command groups), smoke tests in `tests/unit/test_cli.py`, the folder skeleton from PLAN §16 with `.gitkeep` files, `.env.example`, `.pre-commit-config.yaml` (ruff lint + format, gitleaks, end-of-file, whitespace, YAML/TOML, large files), `.github/workflows/ci.yml` (uv sync, ruff, pytest; gitleaks over the full history), `LICENSE` (MIT), README status line and "Development" section. Guilherme's answers to Q1–Q9 are in `OPEN-QUESTIONS.md`; decisions D-35 to D-38 are in `DECISIONS.md`.
- **Not built:** nothing from the prompt is missing. Not done on purpose: `compose.yaml`, `docker/`, `api/`, `web/` (later phases); the plan edits that follow from D-36 (PLAN §6/§7, in P2-01 / P2-02) and D-37 (abstracts, in P1-10). Done in the same PR: Fable replaced by Opus in `WORKFLOW.md`, `ROADMAP.md`, `PLAN.md` and the session prompts (D-35).
- **Surprises:** `pre-commit` and `gitleaks` were not installed on the Mac; both run through `uvx pre-commit` (pre-commit builds gitleaks itself), so nothing was installed system-wide. The Docker daemon was not running, so the full-history scan used the gitleaks binary that pre-commit built (v8.30.0): 1 commit scanned, no leaks. P0-00 is partly done (remote exists, `main` pushed, `gh` logged in) but is not ticked because the GitHub settings could not be checked from here.
- **Hand-off to P0-02:**
  - Run everything with `uv run ...`; the system `python3` is 3.15 and must not be used.
  - `pytest-httpx` is already a dev dependency. Add new dependencies with `uv add` so `uv.lock` stays in step (CI runs `uv sync --locked`).
  - CLI: `flatatlas.cli.groups` is a dict of one Typer sub-app per stage; add commands with `@groups["harvest"].command()`. `status` is an empty **group** today; P0-02 wants `flatatlas status` as a plain command, so replace that group with a command (and keep `tests/unit/test_cli.py` passing: it checks that all 13 names appear in `--help`).
  - `config/` and `config/profiles/` hold only `.gitkeep`; P0-02 writes the first real files there. Remove a `.gitkeep` when its folder gets a real file.
  - `.env` does not exist yet (Guilherme creates it from `.env.example`); tests must not need it. `CONTACT_EMAIL` is answered in OPEN-QUESTIONS Q6.
  - Local hooks: `uvx pre-commit install` once, then `uvx pre-commit run --all-files` before pushing.

### 2026-11-15 — Planning session (Fable)
- **Built:** `CLAUDE.md`, `README.md`, `.gitignore`, and under `docs/plan/`: `PLAN.md`, `WORKFLOW.md`, `ROADMAP.md`, `DECISIONS.md`, `RISKS.md`, `OPEN-QUESTIONS.md`, `sessions/` (39 prompts, 2 manual checklists, gate template).
- **Not built:** no code, no GitHub remote, no CI.
- **Surprises:** OpenAlex now needs a free API key with a $1/day budget (enough for the whole field); abstracts for Springer LNCS venues are likely to be scarce; the CORE portal blocks automated access; the Mac has only 22 GB of free disk.
- **Hand-off to P0-00 / P0-01:** nothing exists except documents. P0-01 creates the Python project from scratch. Python must be pinned to 3.12 (the system has 3.15). `uv`, `git`, `gh`, `node`, `docker` are installed; `ollama` and `tmux` are not.

## Parking lot (ideas outside the current session; do not build)
- "Similar papers" on paper pages using embeddings (needs pgvector; server stage).
- Per-author topic timeline visualisation.
- Wikidata / ROR enrichment for institutions.
- A short dataset paper describing the Atlas.
