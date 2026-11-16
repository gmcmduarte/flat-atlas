# FLAT Atlas: taxonomy and tagging redesign brief

*Written 2026-11-16 from a discussion between Guilherme and Claude (Opus 5.5) in Claude Code.
Purpose: hand to Fable so it can redesign the tagging part of the plan and the session prompts.*

---

## 0. The one constraint that overrides everything

**The project must stay at (almost) zero running cost.** It is a solo, zero-budget, public project.

- The default for every step is **free**: local models, free API tiers, the maintainer's laptop (Apple M1, 16 GB RAM) and later a university server.
- A paid API may only be used as an **opt-in, measured exception**: it must beat the free option on our own evaluation by a meaningful margin, it must sit behind a hard spending cap enforced in code, and it needs a `DECISIONS.md` entry approved by Guilherme. Today hard rule 3 ("no paid APIs") forbids it outright.
- Target if a paid step is ever approved: **under about $15 for a full tag of the whole field, and well under $1 a year for the weekly increments**.
- Never design a step whose cost grows per page view or per user. All paid work, if any, happens once in the batch pipeline.

---

## 1. Project context (short)

The FLAT Atlas is an open map of formal languages and automata theory (1950s to today) linking topics, papers, authors and venues. Python pipeline (`flatatlas` CLI, DuckDB + Parquet), static SvelteKit site for the pilot, PostgreSQL + pgvector + FastAPI later on a university server.

Hard rules that matter for this redesign (from `CLAUDE.md`):
- **Zero running cost** (rule 3).
- **Metadata and links only; abstracts are used locally** and never exported (rule 2).
- **Every automatic assignment stores a `confidence` and a `provenance`** (method + version) (rule 4).
- **Never hand-edit generated data**; only `config/` and `taxonomy/` are human-edited (rule 5).
- **Never overwrite reviewed taxonomy fields**; proposals go to `taxonomy/proposals/` (rule 6).
- **Long jobs run outside Claude sessions**, as scripts Guilherme launches (rule 7).

Relevant existing decisions: D-02 (one-time human review of the topic DAG; paper tagging fully automatic), D-12 (server stack with pgvector), D-13 (no vector database; numpy/DuckDB for similarity), D-27 (evaluation never uses a hand-labelled test set), D-34 (pilot venues DCFS, DLT, CIAA kept despite poor abstract coverage).

Relevant sessions to redesign: P1-05 taxonomy tools, P1-06 taxonomy v1, P1-07 tagger v1, P1-08 propagation and evaluation, P4-05 tagger v2 and release.

---

## 2. Measured facts that shape the design

- **Pilot corpus:** 2,339 papers (DLT 1,025, CIAA 716, DCFS 505, WIA 74, DCAGRS 19).
- **Abstract coverage is very poor:** only **152 of 2,339 (6 %)** have an abstract (OpenAlex only; Crossref gave none; Semantic Scholar comes in P1-03 and may add some). CIAA 0 %, DLT 6 %, DCFS 16 %. Of the 1,416 DLT and CIAA papers from 2003 on, exactly one has an abstract.
- **Reference lists are well covered: 88 %.** Affiliations 87 %.
- **Whole field:** estimated 150,000–300,000 in-scope papers (unverified estimate).

Consequence: we agree that **a title alone is not enough** to place a paper, but for these venues the abstract usually does not exist. The text we give any model must be built from what we do have (see §5.1).

---

## 3. The current plan (PLAN.md §9), in brief

1. **Topic DAG:** seeds from ACM CCS, MSC2020 and OpenAlex topics (codes stored as cross-references only; own names and descriptions) → phrase mining on titles/abstracts → clustering of SPECTER2 embeddings (UMAP + HDBSCAN at 2–3 granularities) → parent links from seed structure, subsumption, head-noun matching, nested clusters and citations → proposal file → **one-time human review** (2–4 h) → `taxonomy/topics.yaml`. Target 150–300 topics in the pilot, 400–900 for the field.
2. **Per-topic artefacts:** phrase dictionary, seed papers, 1–3 embedding centroids, mappings to OpenAlex topics and MSC codes.
3. **Signals per paper × topic:** title phrase match, abstract phrase match, cosine to centroid, cosine to description, OpenAlex topics, MSC codes, citation propagation, author prior, venue prior, optional local LLM.
4. **Fusion v1:** hand-weighted noisy-OR with an agreement bonus. **v2:** logistic regression on silver labels.
5. **Selection:** most specific topics, confidence ≥ 0.35, at most 6 per paper, ancestors added as derived rows.
6. **Evaluation without hand-labelling:** anchor papers, method agreement, coverage, coherence, venue sanity, stability, spot-check report.

---

## 4. What we discussed and concluded

### 4.1 Weakness of the current plan (agreed)

Guilherme's concern: the plan leans heavily on embedding similarity and fixed metrics, which behave differently depending on the type of paper, especially for broad areas. **This is right:**
- Raw cosine scores are **not comparable across topics**. A broad topic has spread-out papers and one centroid represents it badly; a narrow topic is tight. One threshold means different things in each.
- Similarity is weaker for title-only papers, surveys and bridge papers.
- **v1 fusion weights are set by hand**; nothing learns per topic or per paper type how much to trust each signal.
- **There is no real precision/recall measurement.** Anchor papers are famous, easy cases and flatter the tagger.

Partial mitigations already in the plan: embeddings are one signal of about eight; broad topics mostly get their tags from their children; up to 3 centroids per topic; calibration against random papers. Useful but not enough.

### 4.2 Guilherme's alternative: supervised top-down classification (evaluated)

Idea: label a small set by hand at the top level, train a classifier, then repeat for sub-areas inside each topic, getting more specific each level.

Conclusion: **probably better than the current plan at the top levels, worse at the deep ones** if used alone, because:
1. **Errors cascade.** A wrong level-0 answer means the paper never reaches the right sub-area (a well-known failure of top-down hierarchical classifiers).
2. **Papers have several labels and topics have several parents.** A tree of single-choice classifiers handles that badly.
3. **Label cost grows with the number of topics.** About 300 topics × 30 examples ≈ 9,000 labels. Rare topics (tens of papers in the whole field) cannot be trained at all; phrase rules work best there.
4. **Labels go stale** whenever a topic is merged or split.

The good parts are kept in the hybrid below: **a small labelled set**, **learning how much to trust each signal**, and **asking the hierarchy level by level**.

### 4.3 Small labelled set (change to D-27)

- About **400–600 papers labelled at level 0 and level 1** (multi-label allowed).
- Claude drafts the labels; Guilherme reviews them (about 2–3 hours at ~15 s per paper).
- Split: **two thirds for training, one third held out** for real precision/recall. The held-out third is the referee for every method choice below.
- Stored as a human-edited file under `taxonomy/` (e.g. `taxonomy/gold.yaml`), versioned with `taxonomy_version`.
- This changes D-27 ("never a hand-labelled test set") and needs a note on D-02 (paper tagging stays automatic; the labelled set is for training and measurement only).

### 4.4 Decision models (evaluated)

Guilherme proposed using a **decision model**: a model that does not generate text, but returns a probability for each of a fixed set of options.
- **Jev** (TypeSafe): served through third-party gateways (Eden AI, AIMLAPI, Cloudflare, Mixpeek). Question types: choice, score (ordered levels), yes/no. **Not found on Azure.**
- **Microsoft-Decision-1** (Azure, Microsoft Foundry, public preview): built on **Qwen3.5-9B**; about **$0.042 per million input tokens**, output free (secondary sources; Microsoft's page confirms the input price but mentions no free tier; check before relying on it). Reported by Xbox Research as competitive with GPT-5 on 10k feedback items at 80–100× the speed.

Fit: **very good for our question**, "which of these candidate topics fits this paper, with probabilities". Each probability becomes one more signal.

Caveats to design around:
- **Calibration** is the vendors' claim; we must check it on our held-out set.
- **Option order matters** (one report: the top probability moved from ~0.85 to ~0.95 when options were reversed). Shuffle and average.
- **Pin the model version**; aliases like `latest` change behaviour.
- Sending text to Azure: since 94 % of pilot papers have no abstract, the text sent is mostly titles and reference titles (public metadata), which eases the rule-2 concern, but abstracts must still not be sent without an explicit decision.

**The free equivalent:** run an open Qwen model (4–9B) locally (llama.cpp / Ollama / MLX) and read the probability of each option token, **without generating text**. Same idea, zero cost; calibrate it on our labelled set with isotonic regression. This replaces the current §9.5 design (JSON generation), which is slower and harder to calibrate.

### 4.5 Other cheap model families (2025–26) worth knowing

| Type | Examples | Role for us |
|---|---|---|
| Few-label / zero-shot encoders | **GLiClass** (ModernBERT-based, scores many labels in one pass; ~8 examples per label give large gains), **SetFit** | The cheap local classifier trained in step 4 of the cascade |
| Hierarchical encoder heads | HYDRA (EMNLP 2025), path-level alignment (arXiv, Nov 2026) | Only later; they need thousands of labels |
| Scientific embedding models | SPECTER2 (standard baseline), **SciEmbed** (EMNLP 2026 Findings, 66.85 on SciRepEval), SemCSE (65.76 vs SPECTER2 base 65.46) | About +1 point over SPECTER2; worth one test in P1-07 if weights and licence allow |

### 4.6 Keywords

OpenAlex keywords are machine-generated; author keywords from Crossref are sparse. **Not trusted by default.** Measure their precision on the labelled set later and drop them if they are noise. (Parking-lot item.)

### 4.7 Redis (evaluated)

- **For tagging: not useful.** Comparing ~300k papers with ~500 topics is one matrix multiplication in numpy (seconds). A database server adds nothing.
- **For "similar papers to X" and search: a good idea, but not Redis.** Redis 8.4 has hybrid keyword + vector search (`FT.HYBRID`), but D-13 rules out a separate vector database and everything lives in RAM. **Postgres full-text + pgvector (already planned, D-12), merged with reciprocal rank fusion in SQL**, gives the same result with no extra service.
- **For the static pilot:** precompute the top 20 similar papers per paper, and nearest topics per topic, in the pipeline and ship them as JSON. Zero server cost.

---

## 5. Agreed design: a cheap-to-expensive cascade

The aim is the best balance of **low cost, speed and accuracy**: spend effort only where the cheap signals are unsure.

### 5.1 Text given to any model (because abstracts are mostly missing)

**title + venue + year + titles of its ~10 references + abstract if present + Semantic Scholar TLDR if present (local use only).**
What a paper cites describes it better than a missing abstract. For embeddings: use Semantic Scholar's precomputed SPECTER2 vector when available (it may have used text we cannot get); otherwise embed the composite text above locally.

### 5.2 The four steps

| Step | Applies to | Cost | Speed |
|---|---|---|---|
| **1. Signals and shortlist.** All existing signals (phrases, embeddings, OpenAlex, citations, author and venue priors) → ~8 candidate topics per paper. | all papers | free | minutes |
| **2. Learned fusion.** LightGBM (or logistic regression) over the signal scores plus context features (has abstract, number of references, topic size, topic level), trained on the labelled set + silver labels, then isotonic calibration. Learns *when* to trust each signal, e.g. less trust in embeddings for title-only papers or broad topics. | all papers | free | seconds |
| **3. Decision model.** Only where step 2 is unsure (middling confidence or disagreeing signals, expected ~30–40 %). First a *choice* question over ~20 level-0 topics; then a *yes/no* question for each child of the top 2 parents (handles multiple labels and parents; keeping 2 parents limits cascade errors). Options shuffled, results averaged. Output is **one more signal, never an override**. **Default: local Qwen, free.** Azure Decision-1 only as an approved, capped exception (§0). | uncertain papers | free locally | background job, overnight |
| **4. Distil.** Train a small local classifier (GLiClass or SetFit) on step 3's answers + labelled set, so weekly new papers never need the big model. | new papers | free | seconds per week |

Kept from the current plan: two passes for citation propagation; most-specific-topic selection; threshold 0.35 and max 6 topics (re-tune on the held-out set); derived ancestor rows; `confidence` + `provenance` on every row; artefacts frozen per `tagger_version`; full re-tag only on a `taxonomy_version` bump.

**Hierarchy is soft, never hard routing:** a child topic's score is conditioned on its parents' probabilities, several parents allowed. A wrong level-0 guess lowers scores; it does not block the paper.

**Choose by numbers:** P1-07/P1-08 compare (a) current v1 noisy-OR, (b) a top-down classifier, (c) the cascade, on the held-out third of the labelled set, plus the existing checks (anchors, coverage, stability, venue sanity). Keep the winner.

---

## 6. Cost model

Assumptions: ~1,000 tokens per paper (~250 paper text + ~700 options and questions); field ≈ 300k papers; Azure price $0.042 per million input tokens (unverified on the official pricing page); local speeds are rough estimates for a 4–9B model scoring (not generating) on the M1, helped by putting the shared topic options first so they are cached.

| Scenario | Tokens | Azure Decision-1 | Local Qwen on M1 |
|---|---|---|---|
| Pilot, all 2,339 papers | 2.3 M | ≈ $0.10 | ~1–2 h |
| Field, uncertain only (35 % of 300k) | 105 M | ≈ $4.40 | ~30–70 h, overnight runs |
| Field, all 300k papers | 300 M | ≈ $12.60 | ~85–200 h |
| Same with options shuffled 3× | ×3 | up to ≈ $38 | ×3 |
| Re-tag after a taxonomy change | as a full run | ≈ $4–13 each | same hours |
| Weekly new papers (~5k a year), after step 4 | — | < $0.25 a year | minutes |

Electricity for local runs is negligible. Everything except the optional Azure column is **€0**.

**Recommended path:**
1. P1-07: build steps 1–2 and run the **local** decision model on the pilot. Cost €0.
2. Optional, only with Guilherme's approval and a `DECISIONS.md` exception: run Azure Decision-1 on the same 2,339 pilot papers (**≈ $0.10**) to compare on the held-out set.
3. Field scale: if Azure is clearly better, about $5 once for the uncertain papers, behind a hard cap. Otherwise stay local and free.

If a paid step is ever enabled, implement it like the existing OpenAlex budget guard in `flatatlas.http`: a spending counter, a hard cap from `config/`, a clean stop before the cap, and a run log of tokens and dollars.

---

## 7. Decisions to add or change

- **D-27 → amended:** a small labelled set (§4.3) is allowed for training and held-out evaluation.
- **D-02 → note:** paper tagging stays automatic; the labelled set does not tag papers directly.
- **New:** tagger design is the cascade of §5 (local decision model by default; learned fusion; distilled classifier for increments).
- **New, only if approved:** a narrow exception to hard rule 3 for a capped decision-model API (§0, §6), with abstracts not sent unless separately decided.
- **Unchanged:** D-12 and D-13 (no Redis; pgvector hybrid search for "similar papers" at the server stage; precomputed neighbours in the pilot).
- PLAN §9.4 (fusion), §9.5 (local LLM → local decision-style scoring), §9.6 (evaluation adds the held-out set) need rewriting; `tagger.yaml` gains settings for the cascade.

---

## 8. What we ask Fable to do

1. Redesign PLAN.md §9 (taxonomy and tagging) around the cascade, **keeping the near-zero cost constraint explicit in every step**.
2. Rewrite the session prompts P1-05, P1-06, P1-07, P1-08 and P4-05 accordingly; add a session (or a step in P1-06) for building and reviewing the labelled set.
3. Draft the `DECISIONS.md` entries listed in §7 for Guilherme to approve.
4. Keep everything that already works: the topic-DAG construction, the one-time review, frozen artefacts per version, provenance and confidence, evaluation checks.
5. Do not introduce any service, API or infrastructure with a running cost.

---

## 9. Open questions and unverified items

- Azure Decision-1 price, free tier, context length, batch API and whether weights are released: from secondary sources; check Microsoft's official pages.
- Jev is not on Azure; its pricing is also from a blog.
- Local throughput on the M1 for a 4–9B model doing option scoring: estimate; measure in P1-07.
- Whole-field size (150k–300k) is an estimate.
- Semantic Scholar abstract and TLDR coverage for the pilot: measured in P1-03.
- SciEmbed weights and licence: check before testing.
- Whether keywords carry signal: measure on the labelled set.

---

## Sources

- Jev: <https://www.getmaxim.ai/bifrost/blog/jev-a-decision-model-that-classifies-without-generating-text>
- Microsoft-Decision-1: <https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/introducing-microsoft-decision-1-in-microsoft-foundry-for-decision-and-classific/4562742>
- Decision-1 listing (Requesty): <https://www.requesty.ai/models/azure/decision-1-swedencentral>
- GLiClass: <https://arxiv.org/html/2508.07662v1>, <https://huggingface.co/blog/Ihor/refreshing-zero-shot-classification>
- SetFit + ModernBERT: <https://moshewasserblat.medium.com/new-results-on-setfit-modernbert-for-text-classification-with-few-shot-training-53c154df7c0e>
- HYDRA: <https://aclanthology.org/2025.emnlp-main.472.pdf>
- Path-level alignment: <https://arxiv.org/abs/2611.12420>
- Hierarchical classification of scientific documents: <https://arxiv.org/pdf/2211.02810>
- SciEmbed: <https://aclanthology.org/2026.findings-emnlp.2057/>
- SemCSE: <https://arxiv.org/pdf/2507.13105>
- SciRepEval: <https://arxiv.org/pdf/2211.13308>
- Redis 8.4 hybrid search: <https://redis.io/blog/redis-8-4-open-source-ga/>
- Pilot coverage: `docs/plan/RISKS.md` (R1), `reports/coverage-pilot.md`
