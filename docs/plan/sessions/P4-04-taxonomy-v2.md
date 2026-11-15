# P4-04 — Taxonomy v2 on the full corpus (Opus + Guilherme's review)

**Tool:** Claude Code · **Model:** **Opus** · **Branch:** `s/P4-04-taxonomy-v2` · **Depends on:** P4-03

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §9.1, §9.6
4. `taxonomy/topics.yaml` (structure and level 0–1 only, via a summary command)
5. `docs/plan/reviews/G1-review.md` and `G2-review.md` (tagging findings)

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Extend the reviewed DAG to the whole field without disturbing what Guilherme already reviewed.

## Build
- Run `taxonomy mine`, `cluster`, `propose` on the full in-scope corpus (I launch if long). Proposals to `taxonomy/proposals/v2.yaml`.
- Draft additions area by area: ω-automata and games, automata in verification, weighted and probabilistic automata, transducers, tree/graph/picture languages, combinatorics on words and symbolic dynamics, cellular automata, membrane and DNA computing, grammatical inference, logic and automata, historical topics. Deepen shallow areas marked `proposed`.
- Find and fix structural problems with data: topics too big (> 8 % of the corpus and splittable), too small (< 15 works after tagging), siblings that the tagger cannot separate (high confusion), orphan clusters with no topic.
- Respect `reviewed: true`: do not change reviewed names, parents or phrases; put any suggested change to a reviewed topic in a separate 'suggested edits' list with the evidence.
- Extend `anchors.yaml` to ≥ 150 with every level-0 topic covered by ≥ 5 anchors, each resolved to an identifier in the corpus.
- Write `docs/notes/taxonomy-v2-review-guide.md`; stop for Guilherme's review (2–3 hours); apply his edits; bump `taxonomy_version`.

## Test
- `uv run flatatlas taxonomy check` passes; anchors resolve; a dry-run tag on a 5,000-work sample shows no topic with zero works.

## Done when
- 400–900 topics, 15–25 at level 0, no cycles.
- Reviewed fields unchanged except by Guilherme.
- ≥ 150 anchors, all in the corpus, all level-0 topics covered.
- Guilherme's review committed.

## Out of scope
- Tagger changes (P4-05).

## At the end
- Run `uv run pytest` and `uv run flatatlas taxonomy check` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P4-04, add a dated entry (built, not built, surprises) and a hand-off note for P4-05 (Opus).
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
