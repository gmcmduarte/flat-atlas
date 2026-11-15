# P1-08 — Propagation, evaluation harness, spot-check report

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P1-08-propagation-eval` · **Depends on:** P1-07

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §9.3 (prop signals), §9.4 (two passes), §9.6 (all)
4. `docs/notes/tagger-experiments.md`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
The second tagging pass using the citation and co-authorship graphs, and the full evaluation that replaces hand-tagging.

## Build
- `tagging/propagate.py`: `prop_cite` (weighted mean of pass-1 topic vectors of references and in-corpus citers, references weighted higher, influential citations boosted) and `prop_author` (authors' topic distribution within ±5 years, excluding the work itself). Pass 2 fusion; one iteration only.
- `evaluate/` implementing every check of PLAN §9.6: anchors, method agreement (lexical-only vs embedding-only vs source-only), coverage, coherence (NPMI of top title terms; intra-topic cosine vs random), venue sanity (`expected_topics`), citation consistency, stability across two seeds, hold-out leak test. Thresholds in `config/tagger.yaml`. Results to `ops_quality_report`; non-zero exit when a hard threshold fails.
- `reports/eval-<run>.html`: one self-contained HTML file: summary table with pass/fail, per-topic table sortable by agreement and coherence, and per topic 10 random, 10 lowest-confidence and 10 strongest-disagreement works with links to DOI/DBLP. Readable in 15 minutes.
- Tune `config/tagger.yaml` weights against the automatic checks only (no manual labels), and write what changed and why.

## Test
- Unit tests: propagation on a 6-node toy graph; each metric on synthetic data with a known answer; the evaluation command exits non-zero when anchors are broken on purpose.

## Done when
- Anchors ≥ 90 %, coverage ≥ 85 %, stability ≥ 95 %; or each miss explained with a concrete fix list.
- The HTML report exists; I have opened it.
- Propagation improves or keeps anchor accuracy and coverage (before/after table).

## Out of scope
- Weakly supervised tagger v2 (P4-05). The optional LLM signal (only if gate G1 asks for it).

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-08, add a dated entry (built, not built, surprises) and a hand-off note for P1-09.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
