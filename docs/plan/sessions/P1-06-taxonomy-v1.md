# P1-06 — Taxonomy v1 and anchor papers (Opus + Guilherme's review)

**Tool:** Claude Code · **Model:** **Opus** · **Branch:** `s/P1-06-taxonomy-v1` · **Depends on:** P1-05

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §6 (field guards), §9 intro, §9.1, §9.2, §9.6 (anchors row and "The labelled set")
4. `docs/notes/taxonomy-review-v1.md` and `taxonomy/proposals/v1.yaml`
5. `taxonomy/seeds/*.yaml`
6. `reports/coverage-pilot.md` (summary)

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
The first human-reviewed topic DAG and the anchor-paper list. Your FLAT knowledge matters here: produce a taxonomy a researcher in the field would recognise, covering the **whole field** at the top levels even though the pilot corpus only fills part of it.

## Cost
€0. Lookups go through `SourceClient` (cache first, free tiers). No model API.

## Build
- Draft `taxonomy/topics.yaml`: 15–25 level-0 topics for all of FLAT (classical automata and regular languages, context-free languages and grammars, descriptional and state complexity, operations on languages, algebraic theory, ω-automata and games, automata for verification, weighted and probabilistic automata, transducers, tree/graph/picture languages, combinatorics on words, symbolic dynamics and cellular automata, natural computing (membrane, DNA), grammatical inference, logic and automata, and so on: decide the cut yourself and justify it). Below that, 150–300 topics where the pilot corpus gives evidence; leave areas without pilot evidence shallow and mark them `status: proposed`.
- For each topic: id (slug), name, aliases, 1–3 sentence description in our own words, parents (several where honest: for example shuffle under both operations on languages and combinatorics on words), `include_phrases` with spelling variants and synonyms, `exclude_phrases` for known false friends, xrefs, `origin`.
- Use the proposal evidence; do not invent topics the corpus contradicts; do not copy CCS or MSC text.
- **Levels 0 and 1 carry extra weight:** the labelled set (P1-06b) is labelled at exactly these two levels and the decision model asks about them by name and description. Give every level-0 and level-1 topic a one-line description that separates it from its siblings, and keep level 1 to a size a person can choose from (roughly 60–120 topics in total).
- Draft `taxonomy/anchors.yaml`: ≥ 80 well-known papers with the topic each must land in. Include classics across the field and at least 40 that are in the pilot corpus (DLT/CIAA/DCFS papers that are unambiguous for their topic: find them by querying the warehouse). Anchors are easy cases by design: they catch breakage and check deep levels; precision and recall come from the labelled set, not from them. Resolve every anchor to a DOI or DBLP key by looking it up through `SourceClient`; drop any you cannot resolve. Never write a DOI from memory without checking it.
- `config/venues.yaml`: fill `expected_topics` for the three pilot venues (venue sanity check).
- Run `flatatlas taxonomy check` until clean.
- Write `docs/notes/taxonomy-v1-review-guide.md` for Guilherme: the 10 decisions you were least sure of, areas that are shallow, and how to edit the YAML.
- **Stop here and hand over to Guilherme.** He edits `topics.yaml` and `anchors.yaml` (VS Code). When he returns: apply `reviewed: true` to topics he touched or approved, run `check`, summarise his changes.

## Test
- `uv run flatatlas taxonomy check` passes.
- A script lists anchors and whether each is in the corpus.

## Done when
- `topics.yaml` passes the check; 15–25 level-0 topics; every topic has a description and ≥ 3 phrases or ≥ 2 seed works.
- ≥ 80 anchors, all resolved to real identifiers; ≥ 40 in the pilot corpus.
- Guilherme's review is committed and topics carry `reviewed: true`.
- The DAG has no cycles and multi-parent topics are intentional (listed).
- Every level-0 and level-1 topic has a one-line description that distinguishes it from its siblings.

## Out of scope
- Tagger code. The labelled set `taxonomy/gold.yaml` (P1-06b: it needs the reviewed topic ids, so it starts only after this PR is merged). Changing the proposal tools (note problems for a follow-up instead).

## At the end
- Run `uv run pytest` and `uv run flatatlas taxonomy check` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-06, add a dated entry (built, not built, surprises) and a hand-off note for P1-06b (Opus), listing the level-0 and level-1 topic counts and the topics Guilherme found hard to tell apart.
- Set `taxonomy_version: 1` and record the top-level cut and its reasons in DECISIONS.
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
