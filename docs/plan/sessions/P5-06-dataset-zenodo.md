# P5-06 — Citable dataset: releases with a Zenodo DOI

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P5-06-dataset-zenodo` · **Depends on:** P5-05

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §4.7, §10, §15.7
4. `docs/plan/RISKS.md` R3

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Versioned, citable data releases with a clear licence.

## Build
- `release publish`: package a release (Parquet + manifest + `SOURCES.md` + `LICENSE.md` + `CITATION.cff` + a data dictionary generated from the schema models + changelog from manifest diffs) as one archive, with the optional embeddings file and the separate share-alike add-on as separate files.
- Zenodo: use the sandbox first; upload through the Zenodo API with a token from `.env` (I create the Zenodo account and token myself); metadata (title, creators, licence CC BY 4.0, related identifiers to the repo and the sources' papers, version); concept DOI recorded in config after the first real publish. I press the final publish button.
- Site `/cite`: DOI badge, BibTeX for the dataset and for the site, version history from `/api/releases`; footer shows the release version and DOI.
- Licence check script: asserts no abstracts, no CORE ranks, no zbMATH-derived columns in the CC BY file.
- `docs/runbooks/release.md`: the quarterly release procedure.

## Test
- Unit tests for the packager and the licence check.
- A full dry run against the Zenodo sandbox.

## Done when
- A sandbox deposit is complete and correct; the real deposit is published by Guilherme and its DOI is on the site.
- The licence check passes.
- The runbook was followed once.

## Out of scope
- Dataset paper writing.

## At the end
- Run `uv run pytest` and `uv run ruff check .`, and `npm run check`, `npm run test` and `npm run build` in `web/` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P5-06, add a dated entry (built, not built, surprises) and a hand-off note for the G5 gate review (Opus, `GATE.md`).
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
