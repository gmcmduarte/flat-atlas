# P1-08 — Propagation, evaluation harness, method comparison, spot-check report

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P1-08-propagation-eval` · **Depends on:** P1-07b

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §9 intro, §9.3 (prop signals), §9.4, §9.6 (all)
4. `docs/plan/DECISIONS.md` D-61, D-63
5. `docs/notes/tagger-experiments.md`, `docs/notes/gold-v1-report.md`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
The second tagging pass using the citation and co-authorship graphs, the full evaluation including the held-out labelled set, and the decision, by numbers, of which tagging method the pilot ships with.

## Cost
€0. Local computation only; the decision-model answers are read from the cache of P1-07b (no model is loaded unless pass 2 makes new works unsure, and then only through the same local long job).

## Build
- `tagging/propagate.py`: `prop_cite` (weighted mean of pass-1 topic vectors of references and in-corpus citers, references weighted higher, influential citations boosted) and `prop_author` (authors' topic distribution within ±5 years, excluding the work itself). Pass 2 fusion with the `prop_*` features (retrain by the same cross-validation on gold-train); one iteration only.
- Method (b), the top-down baseline of PLAN §9.4: a small classifier per level on the embeddings, trained on gold-train. Keep it minimal; it exists for the comparison.
- `evaluate/` implementing every check of PLAN §9.6: held-out labelled set (precision, recall, F1 at levels 0 and 1, micro and macro, bootstrap 90 % intervals, calibration curve), anchors, method agreement (lexical-only vs embedding-only vs source-only), coverage, coherence (NPMI of top title terms; intra-topic cosine vs random), venue sanity (`expected_topics`), citation consistency, stability across two seeds, hold-out leak test, the by-paper-type split. Thresholds in `config/tagger.yaml`. Results to `ops_quality_report`; non-zero exit when a hard threshold fails.
- **Tune first, then open the held-out set once.** Tune weights, the unsure band, the threshold and the maximum number of topics on gold-train (cross-validation) and the automatic checks only. Write the final settings down. Then run `flatatlas evaluate --heldout` for all methods in one go and do not tune afterwards. If something must change after seeing held-out numbers, say so plainly in the report, because the numbers are then optimistic.
- **Method comparison**, one table in `docs/notes/tagger-experiments.md`: (a) noisy-or, (b) top-down, (c) learned fusion without the decision model, (c) with it; each with and without propagation; held-out metrics with intervals, the paired-difference interval against the simpler neighbour, and the hard checks. Apply the rule of PLAN §9.6: adopt the more complex method only if the paired interval excludes zero and no hard check gets worse. Set `tagger.method` and `tagger.decision_model.enabled` accordingly and record the choice as a decision.
- `reports/eval-<run>.html`: one self-contained HTML file: summary table with pass/fail, the held-out table and calibration curve, per-topic table sortable by agreement and coherence, and per topic 10 random, 10 lowest-confidence and 10 strongest-disagreement works with links to DOI/DBLP. Readable in 15 minutes.

## Test
- Unit tests: propagation on a 6-node toy graph; each metric on synthetic data with a known answer (including multi-label precision and recall, and the bootstrap interval covering a known value); the evaluation command exits non-zero when anchors are broken on purpose; the held-out evaluation refuses to run if any held-out work appears in a training set or seed set.

## Done when
- Anchors ≥ 90 %, coverage ≥ 85 %, stability ≥ 95 % for the adopted method; or each miss explained with a concrete fix list.
- The comparison table exists with intervals, and the adopted method follows from the rule (or the exception is argued and I agreed).
- The held-out numbers of the adopted method are stated as the pilot's precision and recall at levels 0 and 1, with a proposed floor for gate G1.
- The HTML report exists; I have opened it.
- Propagation improves or keeps held-out F1, anchor accuracy and coverage (before/after table).

## Out of scope
- The distilled classifier and incremental mode (P4-05). Any hosted model API (D-67 is not active). Editing `gold.yaml` or `topics.yaml` (label or taxonomy errors found here go to `taxonomy/proposals/`).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-08, add a dated entry (built, not built, surprises) and a hand-off note for P1-09.
- Record any decision you made in `docs/plan/DECISIONS.md` (the adopted method, with the table's key numbers).
- Commit, push the branch and open a PR to `main`. Do not merge.
