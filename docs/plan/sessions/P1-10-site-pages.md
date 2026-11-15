# P1-10 — Site: topic, paper, author, venue pages and search

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P1-10-site-pages` · **Depends on:** P1-09

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §11.1–11.3
4. `web/src/lib/data/` (all files)
5. `web/src/routes/` listing

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
The core browsing experience on real pilot data.

## Build
- Pages `/topic/[id]`, `/paper/[id]`, `/author/[id]`, `/venue/[id]` as specified in PLAN §11.3. Topic page: breadcrumbs for each parent path, children, three separate edge panels, paper list with sort switch, key authors, activity sparkline.
- Components: `PaperList`, `TopicChips`, `ConfidenceBadge` (with a provenance tooltip in plain language built from the provenance struct), `YearSparkline`, `SearchBox`.
- Search with MiniSearch: index loaded lazily; results grouped as topics, authors, venues, papers; keyboard navigation; `/search?q=`.
- Prerender topic and venue pages; client-render paper and author pages from shards (SPA fallback).
- Loading, empty and error states for every page. Responsive layout. Each page has a title and meta description.
- A CI step that builds the site from a small committed sample export (`web/static/data-sample/`), so CI does not need the warehouse. The deploy workflow uses the real export: produce it locally and publish it as a GitHub release asset that the Pages workflow downloads (document this in `docs/runbooks/publish-site.md`).

## Test
- Component tests for `ConfidenceBadge` and `PaperList` sorting.
- One Playwright smoke test: search a topic → open it → open a child → open a paper → open an author.
- Check pages in the browser preview at desktop and mobile widths; run Lighthouse on a topic and a paper page.

## Done when
- The four page types show real pilot data with no console errors.
- Search finds the topic 'state complexity' (or its reviewed name), a known author and a known paper.
- Every tag shows confidence and an understandable provenance.
- Lighthouse accessibility ≥ 90 on topic and paper pages.

## Out of scope
- The map (P1-11). Suggest button and static content pages (P1-12). Venue analytics.

## At the end
- Run `npm run check`, `npm run test` and `npm run build` in `web/` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-10, add a dated entry (built, not built, surprises) and a hand-off note for P1-11.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
