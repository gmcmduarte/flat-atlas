# P3-03 — FastAPI read API and search

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P3-03-api` · **Depends on:** P3-02

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §12 (API bullet)
4. `web/src/lib/data/DataSource.ts` and `types.ts`
5. `src/flatatlas/export/` models

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
A public read-only REST API over the `atlas` views that returns the same shapes as the static JSON.

## Build
- `api/`: FastAPI app, psycopg 3 async pool, plain SQL in `api/queries/*.sql`, response models reused from the export models (shared package or generated), OpenAPI at `/api/docs`.
- Endpoints: `/api/topics`, `/api/topics/{id}`, `/api/topics/{id}/works` (sort, pagination), `/api/works/{id}`, `/api/authors/{id}`, `/api/venues`, `/api/venues/{id}`, `/api/search?q=&type=` (FTS + trigram, grouped results), `/api/map`, `/api/releases` (live version, date, counts), `/api/health`.
- Cross-cutting: pagination limits, ETag/Cache-Control based on the release version, gzip, CORS for the site origin, per-IP rate limit (slowapi or Caddy), structured logs without IP storage beyond rate limiting, redirects for merged IDs (`merged_into`).
- `docker/Dockerfile.api` and compose service `api`.
- Contract test: for a sample of entities, the API payload equals the static JSON for the same release.

## Test
- API tests with a loaded sample release in a Postgres service container: every endpoint, pagination edges, unknown ids (404), merged ids (redirect), search ranking for exact names.
- A simple latency check (p95) with 200 requests per endpoint locally.

## Done when
- All endpoints pass tests in CI.
- Contract test passes.
- p95 under 200 ms locally on pilot-size data.
- OpenAPI page renders.

## Out of scope
- Write endpoints and suggestions (P5-05). Chair-tool endpoints (P5-04). Bridge endpoint (P5-02).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P3-03, add a dated entry (built, not built, surprises) and a hand-off note for P3-04.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
