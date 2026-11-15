# P3-04 — Frontend API mode and the full local stack

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P3-04-web-api-mode` · **Depends on:** P3-03

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §11.1, §12 (deployment), §13
4. `web/src/lib/data/` (all files)

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
The same site runs against the API, and the whole stack starts with one command.

## Build
- Implement `ApiDataSource.ts` against the API; server-side search replaces MiniSearch in API mode; keep `StaticDataSource` working.
- Build modes: `PUBLIC_DATA_SOURCE=static|api`; in API mode choose `adapter-static` with client-side fetching (simplest, same hosting through Caddy) unless you find a strong reason for `adapter-node`; record the choice in DECISIONS.
- `docker/Caddyfile` and compose service `web`: serves the built site, proxies `/api` to the API, compression, security headers (CSP, HSTS, no-sniff, referrer policy), cache headers; automatic HTTPS on a real hostname, local certificate on localhost.
- `docker compose up` brings up db + api + web; a `make` or script target loads the latest release.
- Run the Playwright suite against both modes in CI (static build, and API mode with service containers).

## Test
- Playwright suite green in both modes.
- UI checklist of WORKFLOW §5 item 4 in API mode in the browser preview.

## Done when
- `docker compose up` serves the full site at https://localhost with pilot data.
- Both data-source modes pass the same tests.
- Security headers present (show `curl -I`).

## Out of scope
- Deployment to the real server (P3-05).

## At the end
- Run `uv run pytest` and `uv run ruff check .`, and `npm run check`, `npm run test` and `npm run build` in `web/` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P3-04, add a dated entry (built, not built, surprises) and a hand-off note for P3-05.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
