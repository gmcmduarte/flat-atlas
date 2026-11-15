# P6-01 — Historical gap analysis

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P6-01-gap-analysis` · **Depends on:** Gate G5 passed

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §7.2 (historical list), §3 (zbMATH row)
4. `docs/plan/RISKS.md` R1

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Know exactly what is missing before 1990 and what matters most, before spending effort filling it.

## Build
- Coverage per venue and year: works found vs expected (DBLP counts, Crossref journal issue counts, OpenAlex source counts); list venue-years with no or partial data.
- Most-cited missing works: references from in-scope works that resolve to no corpus work, clustered by normalised citation string or external ID, ranked by number of citing works; split into 'has an ID in some source' and 'unresolved strings'.
- Metadata gaps by decade: abstracts, references, affiliations.
- Check which historical venues of PLAN §7.2 exist in DBLP, OpenAlex, Crossref and zbMATH Open (sample queries through `SourceClient`), with counts.
- `reports/gaps.md`: a ranked fill list (venue/years/source/expected gain) and a recommendation for P6-02 and P6-03.
- Check whether pre-1990 anchors are in the corpus.

## Test
- Unit tests for the reference-clustering and expected-count logic.

## Done when
- `reports/gaps.md` exists with a ranked, concrete fill list.
- Source availability table for each historical venue.
- Missing pre-1990 anchors listed.

## Out of scope
- Filling the gaps (next sessions).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P6-01, add a dated entry (built, not built, surprises) and a hand-off note for P6-02.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
