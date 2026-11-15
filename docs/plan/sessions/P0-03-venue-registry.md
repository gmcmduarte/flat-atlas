# P0-03 — Venue registry and ID registry

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P0-03-venue-registry` · **Depends on:** P0-02

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §4.1, §7, §8.4, §17 (items 1–3)

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
A validated `config/venues.yaml` where adding a venue is only a config change, with the three pilot venues verified against the live sources, and the stable-ID module.

## Build
- Pydantic model + loader for `config/venues.yaml` (fields as in PLAN §7 example, plus `issn`, `publisher`, `special_issue_of`, `expected_topics`). `flatatlas venues check` validates: unique ids, known `successor_of` targets, no cycles, tier values.
- Entries for **DCFS, DLT, CIAA** and their predecessors (WIA for CIAA; DCAGRS and related workshops for DCFS). Verify each against DBLP (stream key, first year, list of editions) and OpenAlex (source IDs; note that LNCS papers may sit under the book-series source) using `SourceClient`. Write what you verified and how in `docs/notes/venues-pilot.md`, with the date.
- `flatatlas venues show <id>`: prints the entry and the number of editions DBLP lists.
- `ids.py`: mint atlas IDs (`W`, `A`, `V`, `E` + short base32) from an anchor (source, id) deterministically; `core_id_registry` table with `merged_into`; `resolve(id)` follows redirects. IDs never change for the same anchor and are never reused.
- `config/venue_facts.yaml` (empty structure): per venue and year: `core_rank`, `submissions`, `accepted`, each with `source_url` and `note`.

## Test
- Unit tests: schema validation errors (duplicate id, unknown successor, cycle); ID determinism; merge redirect chain; registry survives reload.
- Fixture: trimmed real DBLP responses for one edition of each pilot venue saved under `tests/fixtures/dblp/`.

## Done when
- `uv run flatatlas venues check` passes.
- The three venues have verified streams, first years and predecessor links, with the verification note committed.
- ID tests pass.

## Out of scope
- Harvesting papers (P1-01). Other venues (P2-01).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P0-03, add a dated entry (built, not built, surprises) and a hand-off note for P0-04.
- Correct `docs/plan/PLAN.md` §7.1 if a venue fact there was wrong, and note it in DECISIONS.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
