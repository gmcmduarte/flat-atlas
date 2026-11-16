# P1-05 — Taxonomy tooling: seeds, phrase mining, clustering, proposals

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P1-05-taxonomy-tools` · **Depends on:** P1-04

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md`
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §4.3, §9 intro (cost rule), §9.1, §9.2, §9.3 ("Composite text" only), §9.6 ("The labelled set" only), §10 (licence care for CCS and MSC)

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
The tools that turn the corpus and the seed schemes into a *proposed* topic DAG with evidence, ready for Opus to draft and Guilherme to review, plus the file schemas the later tagging sessions rely on. This session builds tools; it does not decide the taxonomy.

## Cost
€0. Local computation and cached metadata only. The two network fetches (background titles, reference titles) go through `flatatlas.http` inside the free budgets, with the budget guard on. No model API of any kind.

## Build
- `taxonomy/seeds/`: `ccs.yaml` (the FLAT-related CCS nodes: fetch the official ACM CCS 2012 file, keep ids and labels for the relevant subtree only, note the source and reuse terms), `msc.yaml` (the codes listed in PLAN §9.1 with our own short wording), `openalex_topics.yaml` (generated: OpenAlex topics received by pilot works with counts; keywords in a separate list marked `trusted: false`).
- Topic YAML schema (pydantic) exactly as the entry format in PLAN §9.1, loader into `core_topic` and `subtopic-of` edges, and `flatatlas taxonomy check`: no cycles, parents exist, unique ids and aliases, every non-root has a parent, phrases not shared by siblings without a context word, reviewed fields unchanged compared with git HEAD unless `--allow-reviewed-edits`.
- **Labelled-set schema** (pydantic) for `taxonomy/gold.yaml` exactly as in PLAN §9.6, a loader into `eval_gold`, and these rules in `taxonomy check` (they pass trivially while the file does not exist): every work resolves to a work ID; every label is an existing topic at level 0 or 1; `split` equals the hash rule (write the rule once, as a function, and test it); `sampling: topup` works are never `heldout`; `taxonomy_version` matches `topics.yaml`; reviewed entries unchanged compared with git HEAD unless `--allow-reviewed-edits`. Do not create `gold.yaml` (P1-06b does).
- **Reference titles.** The warehouse holds the IDs of cited works but not the titles of those outside the corpus. Add `flatatlas harvest reference-titles` (through `SourceClient`: cached, rate-limited, resumable, `--limit`) and a parse step into a staging table. First find the cheapest free route and record it in `docs/notes/sources.md`: `references.title` in the Semantic Scholar batch, or OpenAlex ID batches of 100 for `stg_reference_candidates` (about 150 calls for the pilot). Show me the estimated calls and budget before the full run.
- **Composite text** (`flatatlas/text/composite.py`, PLAN §9.3): one deterministic function per work returning the parts separately (title, venue, year, up to 10 reference titles chosen by the fixed rule, abstract, TLDR) and joined. Stored only under `warehouse/local/`; never exported. Mining, the labelled set (P1-06b) and the tagger (P1-07) all call this one function.
- `taxonomy mine`: candidate phrases from the composite text (reference titles weigh less than the work's own title): n-grams and noun phrases (a light approach is fine: n-grams filtered by POS patterns or stop-word boundaries), c-TF-IDF against a background of non-FLAT theory titles (fetch about 5,000 titles once through OpenAlex and cache them), variant merging (lemmas, hyphens, British/American spelling, Greek-letter names) and embedding-based merge suggestions. Keywords are listed as candidates with their source, never merged in automatically. Output `data/reports/phrases.parquet` with frequency, first year, example works.
- `taxonomy cluster`: UMAP (fixed seed) + HDBSCAN at three granularities on SPECTER2 vectors; c-TF-IDF labels; cluster–seed overlap table. Dependencies (umap-learn, hdbscan, scikit-learn) go in the `ml` extra.
- `taxonomy propose`: combines seeds, phrases and clusters into candidate topics and parent links using the five evidence types of PLAN §9.1 step 4; writes `taxonomy/proposals/v1.yaml` and `docs/notes/taxonomy-review-v1.md` (per topic: name, aliases, proposed parents with evidence, size, 5 example works).
- Everything deterministic given the seed.

## Test
- Unit tests: schema and every `check` rule for topics and for the labelled set (including the split hash rule and the top-up rule); variant merging ('ω-automata' / 'omega automata', 'synchronising' / 'synchronizing', 'shuffle product' / 'shuffle'); subsumption rule on a synthetic co-assignment matrix; determinism of `propose` on a small fixture; the composite text on fixture works with and without abstract, with more than 10 references and with none (same output on every run).

## Done when
- `mine`, `cluster`, `propose` run on the pilot corpus in under 15 minutes total on the Mac.
- The proposal has a plausible size (roughly 100–400 candidates) and the review document is readable.
- Two runs with the same seed give identical proposals.
- `taxonomy check` accepts a valid sample `gold.yaml` fixture and rejects each broken one.
- Reference titles are in the warehouse for ≥ 80 % of the references of pilot works (or the gap is explained); the spend is inside the free budget and reported.
- Show me the composite text of five works I pick.
- Show me the top 40 mined phrases and the largest clusters with their labels.

## Out of scope
- Writing `taxonomy/topics.yaml` (P1-06) or `taxonomy/gold.yaml` (P1-06b). Tagging.

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-05, add a dated entry (built, not built, surprises) and a hand-off note for P1-06 (Opus).
- Record any decision you made in `docs/plan/DECISIONS.md`.
- Commit, push the branch and open a PR to `main`. Do not merge.
