# P1-12 — Suggest-a-change, content pages, polish, pilot launch

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P1-12-launch-pilot` · **Depends on:** P1-11

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §10, §15.6
4. `docs/notes/drafts/` if it exists (site text drafted in Claude chat)

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Make the pilot public-ready: correction channel, transparent methods and sources, a tagged first release.

## Build
- GitHub issue forms in `.github/ISSUE_TEMPLATE/`: wrong-tag, missing-paper, author-merge-split, new-topic, venue-fact (acceptance rate with source), other. `SuggestButton` on topic, paper, author and venue pages builds a pre-filled URL (entity id, name, current value, page URL).
- Pages: `/about`, `/methods` (how scope, taxonomy and tagging work, what confidence means, known limits; in plain language), `/sources` (each source, licence, attribution; include the literal 'Semantic Scholar' attribution), `/cite` (placeholder until the Zenodo DOI exists, plus `CITATION.cff`).
- A visible 'pilot: three venues' banner with the release version and date from the manifest.
- Polish pass: consistent typography and spacing, focus states, colour contrast, favicon, social preview image, 404 page.
- README: link to the live site, a screenshot, a short 'how the data is produced' section.
- Tag `v0.1.0` after merge (tell me the command; I run it).

## Test
- Playwright: the suggest link on each entity type contains the right template and entity id.
- Full UI checklist of `docs/plan/WORKFLOW.md` §5 item 4 in the browser preview; fix what fails.

## Done when
- Suggest links work for all four entity types.
- Methods, Sources, About, Cite pages exist and are accurate against PLAN.
- The live Pages site shows the pilot with the banner.
- No console errors; Lighthouse accessibility ≥ 90 on home, topic, paper.

## Out of scope
- Any new data feature. Server work.

## At the end
- Run `npm run check`, `npm run test` and `npm run build` in `web/` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-12, add a dated entry (built, not built, surprises) and a hand-off note for the G1 gate review (Fable, `GATE.md`).
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
