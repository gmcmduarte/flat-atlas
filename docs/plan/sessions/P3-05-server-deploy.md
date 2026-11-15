# P3-05 — Deploy to the university server

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P3-05-server-deploy` · **Depends on:** P3-04 and P3-00 (server granted)

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §12 (deployment), §13, §14
4. `docs/runbooks/` listing
5. `compose.yaml`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
The site is live on the server, with refresh, backup and restore procedures that have each been run once. Guilherme runs the commands on the server; you prepare and check them.

## Build
- Ask me first for: hostname, OS, CPU/RAM/disk, how Docker is available, firewall rules, whether I have sudo. Adapt to the answers; do not assume.
- `docs/runbooks/server-setup.md`: step by step: users and directories (`/srv/flat-atlas`, `/data`), Docker and Compose, clone, `.env`, pull images from GHCR, `docker compose up -d`, load and activate the latest release, DNS/HTTPS check.
- `deploy/`: systemd units and timers: weekly `flatatlas run --profile server --incremental`, monthly release + load + activate, nightly `pg_dump` of `community` and `ops` to a backup directory with rotation, weekly copy of the latest release to a second location. Each writes to a log that `flatatlas status` summarises.
- `docs/runbooks/deploy.md` (update to a new image), `rollback.md` (previous image, previous release), `restore.md` (from nothing: images + release + community dump).
- A deploy script or GitHub Actions workflow with manual trigger that connects by SSH only if the university allows it; otherwise a documented pull-based update (`git pull && docker compose pull && up -d`).
- Point GitHub Pages at the server (redirect notice) or keep it as a static mirror; decide with me and record it.

## Test
- Dry-run every runbook on the Mac in containers where possible.
- On the server (I run, you verify from the output I paste or over SSH if available): site reachable over HTTPS; a timer triggered by hand; a backup created; a restore into a scratch database.

## Done when
- Public URL serves the Atlas from the server.
- Refresh timer and backup ran once successfully; restore tested once.
- Runbooks match what was actually done.
- No secret was pasted into the session or the repo.

## Out of scope
- Mass import (Phase 4).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P3-05, add a dated entry (built, not built, surprises) and a hand-off note for the G3 gate review (Opus, `GATE.md`).
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
