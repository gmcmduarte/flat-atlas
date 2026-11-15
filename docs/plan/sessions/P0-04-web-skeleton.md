# P0-04 — Web skeleton and GitHub Pages deployment

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P0-04-web-skeleton` · **Depends on:** P0-01

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §11 (all), §2.3

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
A SvelteKit static site deployed to GitHub Pages from CI, showing fixture data through the `DataSource` interface. It proves hosting works before real data exists.

## Build
- `web/`: SvelteKit + TypeScript + `adapter-static` with `fallback: '404.html'`; base path from an env variable so it works under `https://<user>.github.io/flat-atlas/`.
- `src/lib/data/types.ts`: TypeScript types for Topic, Work, Author, Venue, TopicEdge, tags with confidence and provenance, following PLAN §4. `DataSource.ts` interface (`getTopics`, `getTopic`, `getWork`, `getAuthor`, `getVenue`, `search`, `getMap`); `StaticDataSource.ts` reading `static/data/`; a stub `ApiDataSource.ts` that throws 'not implemented'. Selection by `PUBLIC_DATA_SOURCE`.
- Hand-written fixture data in `web/static/data-fixture/` (5 topics with two edge types, 10 works, 5 authors, 1 venue) in the layout of PLAN §11.2.
- Routes: `/` (list of top-level topics for now), `/topic/[id]`, `/about`. A shared layout with header, search box placeholder, footer with source attributions.
- Vitest + one component test; `npm run check` (svelte-check), ESLint, Prettier.
- `.github/workflows/pages.yml`: build and deploy to GitHub Pages on push to `main`; extend `ci.yml` with the web checks.
- Tell me the one manual step (enable Pages with source 'GitHub Actions' in the repo settings) and wait for me to do it.

## Test
- `npm run check`, `npm run test`, `npm run build` pass.
- Open the built site with the browser preview and check `/`, `/topic/<fixture id>`, a deep link reload, and the 404 fallback.

## Done when
- The public Pages URL shows the home page and a fixture topic page.
- Reloading a deep link on Pages works.
- CI runs the web checks.

## Out of scope
- The map, search, real data, styling beyond a clean readable default.

## At the end
- Run `npm run check`, `npm run test` and `npm run build` in `web/` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P0-04, add a dated entry (built, not built, surprises) and a hand-off note for P1-01.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
