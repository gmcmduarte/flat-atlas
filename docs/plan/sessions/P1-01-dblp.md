# P1-01 — DBLP parse from the dump

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P1-01-dblp` · **Depends on:** P0-03

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §3 (DBLP row), §4.2, §5.1–5.2, §7 (intro)
4. `docs/notes/venues-pilot.md`, and D-49 and D-50 in `docs/plan/DECISIONS.md`
5. `src/flatatlas/dblp_dump.py` (the stream reader and the stream index; P0-03)

**Why this prompt differs from the original plan:** DBLP's web API is behind a bot challenge (D-49), so DBLP data comes from the XML dump `data/raw/dblp-dump/dblp.xml.gz` (+ `dblp.dtd`) that Guilherme downloads by hand. There is no network step and no long job in this session.

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
All papers, editions and authors of the pilot venues from DBLP in staging tables. DBLP is the backbone that defines venue membership.

## Build
- `sources/dblp.py`: parse the dump with `flatatlas.dblp_dump.iter_records` (never decompress it to disk, never load the DTD as an external resource). Keep the records of the active venues' streams, and use each venue's `first_year`/`last_year` to split a shared stream (`conf/wia` is WIA and CIAA; `conf/dcfs` is DCAGRS and DCFS). Edition = a `proceedings` record **or** a `crossref` key cited by papers; the edition year is the key's year, not the proceedings record's `year` (publication year).
- Author PIDs are not on paper records: papers carry names (homonyms as `Name 0001`). PIDs come from the `<www key="homepages/…">` person records (PID = the key after `homepages/`, with the name variants listed inside). Verify this against the dump first and record how names are mapped; this needs one pass over the `www` records.
- Parse to `stg_dblp_edition` (venue, year, edition key, title, proceedings DOI from `ee`, ISBNs, publisher, series, volume), `stg_dblp_paper` (dblp key, title, year, pages, DOI extracted from `ee`, type, edition), `stg_dblp_authorship` (dblp key, position, PID, name as printed), `stg_dblp_author` (PID, primary name, ORCID if present).
- Flag front matter and non-papers (`is_front_matter`): 'Front Matter', 'Preface', 'Invited talk abstracts' without pages, etc. Rules in config, not hard-coded.
- CLI: `flatatlas parse dblp [--venue X] [--dump-dir PATH]`; the stage records the dump's MD5 and date in `ops_run_log` so a rerun on a newer dump is visible. (There is no `harvest dblp`.)
- Known gap to handle or report: DCFS 2009 and 2010 exist in DBLP only as CoRR records (`journals/corr/abs-0907-5257`, `abs-1008-1270`), not in `conf/dcfs`. Decide with Guilherme whether to add them (a list of extra keys in `venues.yaml`) or leave them out, and record it.
- A count check: papers per edition against the stream index (`flatatlas venues show`).

## Test
- Parser unit tests on `tests/fixtures/dblp/dblp_sample.xml.gz` (real, from P0-03) plus two awkward cases (a paper with a homonym-suffixed author such as 'Name 0001'; a record without DOI).
- Title normalisation test (accents, LaTeX fragments, trailing period).

## Done when
- Every edition of DCFS, DLT, CIAA and their predecessors is in `stg_dblp_edition`.
- Per-edition paper counts match DBLP (differences listed and explained).
- Share of papers with a DOI reported per venue and decade.
- Show me 10 random rows of `stg_dblp_paper` with authors.

## Running it
Parsing the pilot streams takes a few minutes and uses no network. Prove the command on `--venue dlt` first, then run the full pilot. Show me the command you ran and the log tail.

## Out of scope
- Other sources. Core tables (P1-04). The dump-wide, all-venues load and its orchestration (P4-01).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-01, add a dated entry (built, not built, surprises) and a hand-off note for P1-02.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
