# P3-02 — PostgreSQL serving schema and loader

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P3-02-postgres-loader` · **Depends on:** P3-01

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §4 (all tables in a release), §12 (first two bullets)

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
A release can be loaded into PostgreSQL as a versioned read-only schema and switched live atomically, with rollback.

## Build
- `compose.yaml`: service `db` (PostgreSQL 16 or newer image with pgvector), volume, healthcheck, password from `.env`.
- `export/postgres.py`: `flatatlas export postgres --release vN`: create schema `atlas_vN`; tables generated from the same pydantic export models as the static export (one source of truth); bulk load from Parquet (DuckDB postgres extension or COPY from Arrow); primary and foreign keys; indexes: btree on ids and years, GIN `tsvector` on titles and names, `pg_trgm` on names and titles; optional HNSW on embeddings behind a flag.
- Post-load checks: row counts equal the manifest; foreign keys valid; sample queries return.
- Swap: schema `atlas` contains only views onto the live `atlas_vN`; `flatatlas export postgres --activate vN` re-points all views in one transaction; `--rollback` re-points to the previous one; keep the last 2 loaded versions, drop older ones.
- Schema `community` and `ops` created by a separate idempotent migration (plain SQL files in `api/migrations/`, applied by a tiny runner); the loader never touches them.

## Test
- Integration tests against a Postgres service container (in CI too): load the sample release; counts match; activate; load a second modified release; activate; rollback; `community` tables untouched throughout.

## Done when
- Load, activate and rollback work locally and in CI.
- Loading the pilot release takes under 5 minutes on the Mac.
- Table definitions are generated from the shared models, not hand-written twice.

## Out of scope
- The API (P3-03).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P3-02, add a dated entry (built, not built, surprises) and a hand-off note for P3-03.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
