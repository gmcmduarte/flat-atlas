# P3-01 — Containerise the pipeline

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P3-01-containers` · **Depends on:** Gate G2 passed

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §12 (deployment), §13, §5.4

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
The pipeline runs identically in a container on the Mac and later on the server.

## Build
- `docker/Dockerfile.pipeline`: multi-stage, uv-based, Python 3.12 slim, non-root user, the `ml` extra as a build argument (CPU-only torch wheels for linux/amd64 and arm64).
- `compose.yaml`: service `pipeline` (profile `tools`, run on demand) with the data root as a named volume or bind mount, `.env` passed as environment, never baked into the image.
- `config/profiles/server.yaml` completed: paths under `/data`, concurrency, CPU device, bulk loaders flag.
- CI: build the image on PRs; on `main` push to GHCR with tags `latest` and the git SHA (multi-arch if build time allows, otherwise amd64 plus a local arm64 build instruction).
- `docs/runbooks/run-pipeline.md`: commands for the Mac (native and container) and the server.

## Test
- `docker compose run --rm pipeline flatatlas run --profile pilot --limit 200` end to end on the Mac from a clean clone with only `.env` and an empty data volume.
- Image scan: no `.env`, no `data/` inside the image (`docker history` and a file listing).

## Done when
- The container run above succeeds and produces a release.
- Image published on GHCR from CI.
- Image size reported; base image without ML under 400 MB.

## Out of scope
- Database, API, web containers (next sessions).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P3-01, add a dated entry (built, not built, surprises) and a hand-off note for P3-02.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
