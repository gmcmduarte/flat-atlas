# P1-03 — Semantic Scholar enrichment and embeddings

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P1-03-s2-embeddings` · **Depends on:** P1-02

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §3 (Semantic Scholar row), §4.2 (local tables), §5 stage 5
4. `reports/coverage-pilot.md` (summary)

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
A SPECTER2 vector for every pilot work, more abstracts, and Semantic Scholar citation data.

## Build
- Verify and record in `docs/notes/sources.md`: batch size of `POST /graph/v1/paper/batch`, the embedding field name (`embedding.specter_v2`), accepted ID prefixes (`DOI:`, `DBLP:`), the real rate limit with our key.
- `sources/s2.py` harvest by batch at ≤ 1 request/s: fields corpusId, externalIds, title, year, abstract, tldr, citationCount, influentialCitationCount, references (ids), embedding.specter_v2. Parse to `stg_s2_paper`, `stg_s2_reference`; abstracts into `local_abstract` (priority: OpenAlex, then S2, then Crossref; keep source); vectors into `local_embedding` with `source='s2'`.
- `embed/specter2.py`: local SPECTER2 for works without an S2 vector: `allenai/specter2_base` + the proximity adapter (check the current model card for the exact repo names and the `adapters` library usage); input `title [SEP] abstract` (title only if no abstract); device from the profile (`mps` on the Mac, CPU fallback); batched; resumable; `source='local'`.
- Add torch, transformers, adapters as an optional dependency group `ml` (`uv sync --extra ml`), not in the base install or the base CI job.
- `flatatlas embed [--limit N]` and a comparison command that embeds 50 works locally that also have S2 vectors and reports cosine statistics.
- Store vectors as Parquet `FLOAT[768]`; add a helper for cosine top-k (numpy; no vector DB needed at pilot size).

## Test
- Parser tests on fixtures. Embedding input-formatting test. A tiny-model or mocked test for batching and resume (do not download the model in CI).

## Done when
- Every pilot work has exactly one vector, with its source.
- Local vs S2 mean cosine ≥ 0.9 on the 50-work sample, or the cause is found and recorded.
- Throughput on the M1 measured and written to `docs/notes/sources.md`.
- Disk use of `data/` reported (must stay under 5 GB).

## Long job (Guilherme launches it, not you)
Prove the command works with `--limit 50`. Then give me the exact full command, wrapped as `uv run flatatlas … 2>&1 | tee data/logs/<date>-<name>.log` (on the Mac prefix it with `caffeinate -i`; on the server run it inside tmux). Stop and wait. When I say it finished, read the log tail and `ops_harvest_state`, and continue.

## Out of scope
- Clustering and tagging. Any other embedding model (P1-07 may test one).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-03, add a dated entry (built, not built, surprises) and a hand-off note for P1-04.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
