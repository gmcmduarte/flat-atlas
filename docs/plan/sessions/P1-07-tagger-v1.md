# P1-07 — Tagger v1: artefacts, signals, shortlist, learned fusion

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P1-07-tagger-v1` · **Depends on:** P1-06b

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §4.4, §9 intro, §9.2, §9.3, §9.4, §9.6 ("The labelled set" only), §9.7 (first paragraph)
4. `docs/plan/DECISIONS.md` D-61 to D-65
5. `taxonomy/topics.yaml` and `taxonomy/gold.yaml` (first 80 lines of each for the format)
6. `config/` listing

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Cascade steps 1 and 2: automatic topic tags for every work, each with a calibrated confidence and a provenance, from free signals and a fusion model that learns when to trust each signal. No propagation and no decision model yet.

## Cost
€0. Everything runs on the laptop in minutes. No model API, no network except cached reads. New dependencies (lightgbm, scikit-learn) go in the `ml` extra and must be free and open.

## Build
- `tagging/artefacts.py`: per topic, build and cache (keyed by `taxonomy_version` + `tagger_version`): weighted phrase dictionary (include phrases, aliases, mined variants from `phrases.parquet`, nearest phrases by embedding; ambiguous short phrases need a context word; exclude phrases veto), seed set (`seed_works` + exact title matches, **never a held-out work**), centroid(s) from seed vectors (k-means up to 3 when seeds are spread), description embedding, mapped OpenAlex topics, the topic context features of PLAN §9.2, and the per-topic score distributions for calibration.
- `tagging/signals.py`: `lex_title`, `lex_abstract`, `lex_refs`, `emb_seed`, `emb_desc`, `src_openalex`, `venue_prior` exactly as PLAN §9.3, reading the composite text parts from P1-05. Embedding signals are stored as per-topic percentiles, never raw cosines. Matching on normalised text with word boundaries; fast (Aho–Corasick or compiled regex). Also the per-work context features of §9.3.
- `tagging/shortlist.py`: about 8 candidate topics per work plus ancestors, as PLAN §9.3. Report its recall on gold-train.
- `tagging/fusion.py`:
  - method (a): noisy-or with weights from `config/tagger.yaml` and the agreement bonus;
  - silver labels with the leak rule of PLAN §9.4;
  - method (c): the learned model on pair features (signals, context features, best-parent probability), scored level by level so that the hierarchy is soft; train both LightGBM and logistic regression on gold-train + silver with 5-fold cross-validation **inside gold-train**, keep the simpler unless the other is clearly better; isotonic calibration fitted on out-of-fold predictions;
  - selection (threshold and maximum from config, starting at 0.35 and 6, tuned on gold-train), `is_primary`, ancestors as `derived`.
  - A single guard function used by all training code refuses any work with `split: heldout`; test it.
- Create `config/tagger.yaml` with every weight, band, threshold, seed and model setting; `tagger.decision_model.enabled: false` for now.
- Write `tag_signal` and `tag_work_topic` with the provenance struct (method, signals with scores, model file hash, versions). Model files are saved under `data/` and frozen per `tagger_version`.
- `flatatlas tag [--method noisy_or|fusion] [--limit N] [--explain <work_id>]`: `--explain` prints why a work got its tags (signals, context features, the model's largest contributions).
- Two small experiments, numbers recorded in `docs/notes/tagger-experiments.md`, judged on gold-train by cross-validation:
  1. `emb_desc`: SPECTER2 ad-hoc query adapter vs one small general sentence-transformers model.
  2. For works without an S2 vector: local SPECTER2 on the title alone vs the title plus reference titles.
  Optional third, only if the weights are openly downloadable under a licence that allows this use (check and record it first): SciEmbed against SPECTER2 on the same task. Do not change D-23 here; report the number.

## Test
- Unit tests per signal on tiny fixtures (including exclude phrases, context words, hyphen and spelling variants, a work with no references, a work with no abstract).
- Fusion tests: noisy-or monotonic in each signal; agreement bonus; ancestor closure; maximum-topics rule; the leak rule; the held-out guard; the learned model is deterministic with a fixed seed; calibration output is in [0, 1] and monotonic.
- A regression fixture: 20 works with expected primary topics (taken from anchors).
- The default test run must pass without the `ml` extra (skip the tests that need it); CI installs it in one job.

## Done when
- Every pilot work has tag rows or is listed as untagged, for both methods.
- Shortlist recall on gold-train ≥ 95 %, or the misses are listed by cause.
- ≥ 80 % of in-corpus anchors land in the right topic (top 3) with the learned fusion.
- Cross-validated precision, recall and F1 at levels 0 and 1 on gold-train are in `tagger-experiments.md` for (a) and (c), with the share of works in the unsure band. **No held-out number is computed in this session.**
- Full pilot tagging (steps 1–2, including training) runs in under 10 minutes on the Mac.
- Show me `--explain` for five works I pick.

## Out of scope
- Propagation, the held-out evaluation and the method comparison (P1-08). The decision model (P1-07b). Any hosted model API. Do not edit `topics.yaml` or `gold.yaml` (write suggestions to `taxonomy/proposals/`).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-07, add a dated entry (built, not built, surprises) and a hand-off note for P1-07b: the unsure-band share, the table and column that hold the fused scores, and how a new signal is added to the fusion model.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
