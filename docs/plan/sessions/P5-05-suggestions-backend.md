# P5-05 — Community suggestions backend and moderation queue

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P5-05-suggestions-backend` · **Depends on:** P5-04

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §12 (suggestions bullet), §15.6
4. `api/migrations/` listing

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Visitors suggest corrections on the site; Guilherme moderates; accepted ones flow into the next release with provenance.

## Build
- `community.suggestion` table: id, created_at, type (wrong-tag, missing-paper, merge-authors, split-author, new-topic, venue-fact, other), target kind and id, payload JSON (validated per type), optional contact, status (new/accepted/rejected/applied), moderator note, release_applied.
- `POST /api/suggestions`: validation per type, size limits, honeypot field, per-IP rate limit, no accounts, no IP stored after rate limiting; a plain confirmation page.
- Site: the Suggest button opens an in-page form in API mode (GitHub issue link remains in static mode and as an alternative).
- `/admin`: behind Caddy basic auth (credentials from `.env`): queue with filters, the entity's current state next to the suggestion, accept/reject with note.
- Applying: accepted suggestions are exported by `flatatlas community pull` to `config/overrides.yaml` (tag overrides, author merges/splits, venue facts) or as taxonomy proposals; the pipeline applies overrides after automatic steps and marks provenance `community` with confidence 1.0; `status` becomes `applied` with the release.
- Privacy note on the form and in `/about`.

## Test
- API tests: validation, rate limit, honeypot, admin auth required.
- Pipeline test: an override changes a tag and the provenance; an author merge override is honoured by `resolve`.
- Playwright: submit a suggestion; see it in the queue; accept it.

## Done when
- End-to-end: suggestion → queue → accept → override → next run shows the change with provenance `community`.
- Admin is unreachable without credentials (show `curl`).
- Backups include the `community` schema.

## Out of scope
- User accounts, public discussion threads, email notifications.

## At the end
- Run `uv run pytest` and `uv run ruff check .`, and `npm run check`, `npm run test` and `npm run build` in `web/` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P5-05, add a dated entry (built, not built, surprises) and a hand-off note for P5-06.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
