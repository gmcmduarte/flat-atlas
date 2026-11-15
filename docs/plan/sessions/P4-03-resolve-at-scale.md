# P4-03 — Entity resolution at scale (Opus)

**Tool:** Claude Code · **Model:** **Opus** · **Branch:** `s/P4-03-resolve-at-scale` · **Depends on:** P4-02

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §8 (all)
4. `reports/resolve-*.md` (latest)
5. `config/resolve.yaml`
6. `docs/plan/RISKS.md` R5

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Trustworthy works, authors and venues across the whole field, including authors outside DBLP and renamed venues.

## Build
- Measure first: sample 100 conference/journal merges and 100 author mappings from the full run; judge each with reasons; compute precision; list failure patterns.
- Improve version merging for patterns found (special issues, title changes between versions, two-part papers that must *not* merge, proceedings reprints, arXiv versions).
- Authors not in DBLP: implement the provisional-author path of PLAN §8.3 (OpenAlex or zbMATH author IDs, name + coauthor overlap); flag low confidence; make chair tools and key-author lists ignore authors below 0.8.
- Detect likely DBLP homonym pages that are not disambiguated (very long careers, disjoint topic and coauthor clusters); flag, never split automatically.
- Venue successions and several OpenAlex source IDs per venue: verify analytics 'with predecessors' on Information and Control → Information and Computation and on EIK → JALC.
- Blocking and performance so `resolve` on the full corpus runs in under 1 hour on the server.
- An uncertain-case report designed to feed community suggestions later.

## Test
- Add regression fixtures for every failure pattern fixed.
- Re-sample 100 + 100 after the changes.

## Done when
- Merge precision ≥ 95 % and author-mapping precision ≥ 95 % on the new samples (judgments saved in `reports/`).
- No two DBLP PIDs merged; provisional authors flagged.
- `resolve` is deterministic and within the time budget.

## Out of scope
- Taxonomy and tagging.

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P4-03, add a dated entry (built, not built, surprises) and a hand-off note for P4-04 (Opus).
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
