# P1-04 — Entity resolution, core tables, data-quality tests

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P1-04-resolve` · **Depends on:** P1-03

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §4.1–4.2, §4.6, §8 (all)
4. `src/flatatlas/ids.py`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
The resolved `core_*` tables: one work per intellectual work, authors anchored on DBLP PIDs, venues and editions, in-corpus citations. With quality checks that fail loudly.

## Build
- `resolve/venues.py`: `core_venue`, `core_edition` from the registry and DBLP staging.
- `resolve/works.py`: cross-source join per PLAN §8.1 (DOI, DBLP key ↔ S2 external id, fuzzy fallback with rapidfuzz); field precedence rules; `core_version`. Then conference/journal merging per §8.2: candidate generation, score from title similarity (after stripping 'extended abstract' etc.), author Jaccard, embedding cosine, journal-cites-conference; thresholds in `config/resolve.yaml`; merge ≥ 0.85, report 0.5–0.85, never merge below. In the pilot corpus journal versions are mostly absent, so also write the logic to attach a journal version *found through references or S2/OpenAlex 'versions'* later; keep it tested on synthetic pairs.
- `resolve/authors.py`: `core_author` from DBLP PIDs; map OpenAlex and S2 author IDs onto PIDs by shared papers and position/name alignment (§8.3); `core_authorship` with affiliation, institution and country from OpenAlex; `core_institution`.
- `core_citation` for edges with both ends in the corpus (union of OpenAlex and S2 references, `sources[]`, `is_influential`).
- Mint atlas IDs through the registry for works, versions, authors, venues, editions.
- `tests/data_quality/`: checks run by `flatatlas evaluate --data`: unique DOIs across works; every version has venue and year; no orphan authorships; counts per edition equal staging; no author with two PIDs; merge-confidence histogram; share matched per source. Results to `ops_quality_report`.
- `reports/resolve-pilot.md`: 30 random merges with the evidence, all uncertain pairs, authors with low mapping agreement.

## Test
- Unit tests for every rule with small synthetic fixtures: DOI case differences; same title different papers (must not merge); conference + journal pair (must merge); homonym authors (must not merge); author ID mapping with conflicting evidence.

## Done when
- `core_*` tables exist with the columns of PLAN §4.2.
- All data-quality checks pass.
- I have read the 30 sampled merges and the uncertain list.
- Re-running `resolve` gives identical IDs and tables.

## Out of scope
- Scope (all pilot papers are Tier A `core`; just set the column). Topics and tags.

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-04, add a dated entry (built, not built, surprises) and a hand-off note for P1-05.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
