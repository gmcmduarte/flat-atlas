# P0-01 — Project scaffold, tooling and CI

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P0-01-scaffold` · **Depends on:** P0-00 (manual setup done)

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §1 and §16

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
A reproducible Python project with a CLI, linting, tests, secret scanning and CI, so every later session starts from a working base.

## Build
- `pyproject.toml` managed by **uv**, Python pinned to 3.12 (`.python-version`); package `src/flatatlas/`; `uv.lock` committed.
- Dependencies now: typer, pydantic, pydantic-settings, httpx, duckdb, pyarrow, pyyaml, rapidfuzz, tenacity. Dev: pytest, pytest-httpx, ruff.
- `src/flatatlas/cli.py`: Typer app `flatatlas` with `--version` and empty command groups: harvest, parse, resolve, scope, embed, taxonomy, tag, evaluate, aggregate, release, export, status, venues.
- Folder skeleton from PLAN §16 (`config/`, `config/profiles/`, `taxonomy/`, `tests/unit`, `tests/fixtures`, `tests/data_quality`, `scripts/`, `docs/notes/`, `docs/runbooks/`) with `.gitkeep` files.
- `.env.example` with `OPENALEX_API_KEY=`, `S2_API_KEY=`, `CONTACT_EMAIL=`, `FLATATLAS_PROFILE=pilot`, `FLATATLAS_DATA_ROOT=./data`. Check that `.gitignore` already ignores `.env` and `data/`.
- `.pre-commit-config.yaml`: ruff (lint + format), gitleaks, end-of-file and YAML checks.
- `.github/workflows/ci.yml`: on push and PR: uv sync, ruff, pytest, gitleaks.
- `LICENSE` (MIT, holder Guilherme Duarte). Update the README status line and add a 'Development' section with the commands.

## Test
- One smoke test: the CLI `--help` exits 0 and lists all command groups.
- Run pre-commit on all files.

## Done when
- `uv sync && uv run pytest && uv run ruff check .` pass on a clean clone.
- `uv run flatatlas --help` lists the command groups.
- CI is green on the PR.
- gitleaks finds nothing in the full history.

## Out of scope
- Any source client, any data code, the frontend.

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P0-01, add a dated entry (built, not built, surprises) and a hand-off note for P0-02.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
