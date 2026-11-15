# P1-01 — DBLP harvest and parse

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P1-01-dblp` · **Depends on:** P0-03

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §3 (DBLP row), §4.2, §5.1–5.2
4. `docs/notes/venues-pilot.md`
5. `src/flatatlas/http.py` (public interface only)

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
All papers, editions and authors of the pilot venues from DBLP in staging tables. DBLP is the backbone that defines venue membership.

## Build
- `sources/dblp.py` harvest: for each active venue, list its editions/volumes from the DBLP stream, then fetch the records of each edition (JSON or XML API; choose the one that returns author PIDs and `ee` links reliably, and record the choice). ≤ 1 request/s. Everything through `SourceClient`.
- Parse to `stg_dblp_edition` (venue, year, toc key, title, proceedings DOI/ISBN), `stg_dblp_paper` (dblp key, title, year, pages, DOI extracted from `ee`, type, edition), `stg_dblp_authorship` (dblp key, position, PID, name as printed), `stg_dblp_author` (PID, primary name, ORCID if present).
- Flag front matter and non-papers (`is_front_matter`): 'Front Matter', 'Preface', 'Invited talk abstracts' without pages, etc. Rules in config, not hard-coded.
- CLI: `flatatlas harvest dblp [--venue X] [--limit N]`, `flatatlas parse dblp`.
- A count check: papers per edition vs the number of entries DBLP lists for that edition.

## Test
- Parser unit tests on the fixtures from P0-03 plus two awkward cases (a paper with a homonym-suffixed author such as 'Name 0001'; a record without DOI).
- Title normalisation test (accents, LaTeX fragments, trailing period).

## Done when
- Every edition of DCFS, DLT, CIAA and their predecessors is in `stg_dblp_edition`.
- Per-edition paper counts match DBLP (differences listed and explained).
- Share of papers with a DOI reported per venue and decade.
- Show me 10 random rows of `stg_dblp_paper` with authors.

## Long job (Guilherme launches it, not you)
Prove the command works with `--limit 50`. Then give me the exact full command, wrapped as `uv run flatatlas … 2>&1 | tee data/logs/<date>-<name>.log` (on the Mac prefix it with `caffeinate -i`; on the server run it inside tmux). Stop and wait. When I say it finished, read the log tail and `ops_harvest_state`, and continue.

## Out of scope
- Other sources. Core tables (P1-04). The DBLP XML dump (P4-01).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-01, add a dated entry (built, not built, surprises) and a hand-off note for P1-02.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
