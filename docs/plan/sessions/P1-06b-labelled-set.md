# P1-06b — The labelled set: sample, draft labels, Guilherme's review

**Tool:** Claude Code · **Model:** **Opus** · **Branch:** `s/P1-06b-labelled-set` · **Depends on:** P1-06 (merged, with Guilherme's taxonomy review)

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §9 intro, §9.3 ("Composite text" only), §9.6 ("The labelled set")
4. `docs/plan/DECISIONS.md` D-02, D-27, D-61, D-62
5. `taxonomy/topics.yaml`: all level-0 and level-1 topics (names, descriptions, parents)

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
`taxonomy/gold.yaml`: 400–600 pilot works labelled at level 0 and level 1, drafted by you and reviewed by Guilherme, split into a training part and a held-out part. It is the only real measure of precision and recall the project has, so how it is sampled and reviewed matters more than its size.

## Cost
€0. You draft the labels in this session; no script calls a model API. Guilherme's time: about 2–3 hours.

## Build
- `flatatlas gold sample --n 500 --seed <s>`: a random sample of in-scope pilot works, stratified by venue, decade and has-abstract (proportional, with a minimum of 3 per non-empty cell). The sample must **not** depend on any tagger, signal, phrase match or cluster. Write the sampling frame counts and the seed to the run log. Deterministic.
- Mark 50 of the sampled works `blind: true` (chosen by hash).
- `flatatlas gold sheet`: write the review files from the sample, using the composite text function of P1-05:
  - `data/review/gold-blind.md`: the 50 blind works, **without** draft labels, each with title, venue, year, reference titles, abstract or TLDR if present, a link to the DOI or DBLP page, and an empty `labels:` line. Below it, the list of level-0 and level-1 topic ids with their one-line descriptions.
  - `taxonomy/proposals/gold-draft.yaml`: all works in the PLAN §9.6 format with your draft labels and `reviewed: false`.
- **Draft the labels yourself**, in batches, from the composite text and your knowledge of the field: every level-0 and level-1 topic that applies (usually 1–3 at each level). A level-1 label implies its level-0 parent; list both. Use `note:` for works you are unsure of and say why. Do not look at any tagger output. Do not draft the 50 blind works until Guilherme has handed in `gold-blind.md`.
- Write `docs/notes/gold-review-guide.md` for Guilherme: what a label means (the paper is *about* the topic, not merely mentioning it), how to handle surveys and bridge papers, how to edit the YAML, the 30 works you were least sure of, and the order of work: blind file first, then the draft.
- **Stop here and hand over to Guilherme.** He fills `gold-blind.md` first (about 15 minutes), then reviews `gold-draft.yaml` in VS Code (about 15 s per work).
- When he returns: `flatatlas gold finalise` reads his files, sets `split` by the hash rule of P1-05 (two thirds `train`, one third `heldout`), sets `reviewed: true`, and writes `taxonomy/gold.yaml`. Never change a label he set.
- Report, in `docs/notes/gold-v1-report.md`: counts per level-0 and level-1 topic in each split; labels per work; share of your draft labels he changed (by level); agreement between his blind labels and your draft on the 50 blind works (Jaccard per work, and per-level precision and recall of the draft against the blind labels); level-1 topics with fewer than 5 training examples.
- **Top-up (only if needed):** for level-1 topics with fewer than 5 training examples, propose up to 100 extra works found by title search, marked `sampling: topup`; Guilherme reviews them the same way. They are training only and never enter the held-out part.

## Test
- Unit tests: the sample is deterministic, hits the stratum quotas on a fixture, and is unchanged when tag tables are present or absent; `finalise` keeps reviewed labels byte for byte and refuses to run if a label is not a level-0 or level-1 topic.
- `uv run flatatlas taxonomy check` passes with `gold.yaml` in place.

## Done when
- `taxonomy/gold.yaml` has 400–600 reviewed works with `sampling: random`; every one has at least one level-0 label; about one third are `heldout`; no top-up work is `heldout`.
- The blind subset was labelled before the draft was seen, and the agreement numbers are in the report.
- Every level-0 topic that occurs in the pilot corpus has at least 5 held-out works, or is listed as too small to measure.
- Guilherme's review is committed.

## Out of scope
- Tagger code. Editing `topics.yaml` (write taxonomy problems that the labelling exposed to `taxonomy/proposals/`; if they are serious, stop and tell me, because the taxonomy should be fixed before the labels are final). Labelling below level 1.

## At the end
- Run `uv run pytest`, `uv run ruff check .` and `uv run flatatlas taxonomy check` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-06b, add a dated entry (built, not built, surprises) and a hand-off note for P1-07 (Sonnet): the split sizes, the thin topics, and the reminder that held-out works are excluded from training, calibration, tuning and seed sets.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
