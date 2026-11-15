# P1-07 — Tagger v1: artefacts, signals, fusion

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P1-07-tagger-v1` · **Depends on:** P1-06

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §4.4, §9.2, §9.3, §9.4 (v1 only), §9.7
4. `taxonomy/topics.yaml` (first 80 lines for the format)
5. `config/` listing

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Automatic topic tags for every work, each with a confidence and a provenance, using the free signals. No propagation yet.

## Build
- `tagging/artefacts.py`: per topic, build and cache (keyed by `taxonomy_version` + `tagger_version`): weighted phrase dictionary (include phrases, aliases, mined variants from `phrases.parquet`, nearest phrases by embedding; ambiguous short phrases need a context word; exclude phrases veto), seed set (`seed_works` + exact title matches), centroid(s) from seed vectors (k-means up to 3 when seeds are spread), description embedding, mapped OpenAlex topics/keywords.
- `tagging/signals.py`: `lex_title`, `lex_abstract`, `emb_seed` (cosine calibrated to a percentile against random works), `emb_desc`, `src_openalex`, `venue_prior` exactly as PLAN §9.3. Matching on normalised text with word boundaries; fast (Aho–Corasick or compiled regex).
- A small experiment for `emb_desc`: SPECTER2 ad-hoc query adapter vs one small general sentence-transformers model on the anchors; keep the better, record numbers in `docs/notes/tagger-experiments.md`.
- `tagging/fusion.py`: noisy-or with weights from `config/tagger.yaml`, agreement bonus across signal families, hierarchy rule (most specific; ancestors as `derived`), selection (threshold 0.35, max 6, `is_primary`).
- Write `tag_signal` and `tag_work_topic` with the provenance struct (method, signals with scores, versions).
- `flatatlas tag [--limit N] [--explain <work_id>]`: `--explain` prints why a work got its tags.

## Test
- Unit tests per signal on tiny fixtures (including exclude phrases, context words, hyphen and spelling variants).
- Fusion tests: monotonic in each signal; agreement bonus; ancestor closure; max-6 rule.
- A regression fixture: 20 works with expected primary topics (taken from anchors).

## Done when
- Every pilot work has tag rows or is listed as untagged.
- ≥ 80 % of in-corpus anchors land in the right topic (top 3).
- Full pilot tagging runs in under 10 minutes on the Mac.
- Show me `--explain` for five works I pick.

## Out of scope
- Propagation, evaluation harness, weak supervision (later sessions). Do not edit `topics.yaml` (write suggestions to `taxonomy/proposals/`).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-07, add a dated entry (built, not built, surprises) and a hand-off note for P1-08.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
