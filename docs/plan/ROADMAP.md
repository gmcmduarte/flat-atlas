# Roadmap

39 build sessions in 7 phases, plus 2 manual checklists and 6 gate reviews.
Each session is one model session of work (about 1–3 hours of your attention including review). Each has a ready-to-paste prompt in `sessions/<id>-*.md`.

Legend: **CC** = Claude Code (desktop app or terminal). **S** = Sonnet, **O** = Opus. 👤 = needs you for more than plan/diff review. ⏳ = includes a long job you launch.

| Phase | Goal | Sessions | Where it runs |
|---|---|---|---|
| 0 | Repo, tooling, CI, harvest core, web skeleton | 4 (+1 manual) | Mac |
| 1 | **Pilot**: DCFS, DLT, CIAA end to end on the static site | 12 | Mac + GitHub Pages |
| 2 | Widen: remaining core venues, scope rule, venue analytics | 4 | Mac + GitHub Pages |
| 3 | Server stage: containers, Postgres, API, deployment | 5 (+1 manual) | Mac first, then server |
| 4 | Mass import of the field | 5 | Server |
| 5 | Additional features | 6 | Server |
| 6 | Historical gaps (before about 1990) | 3 | Server |

Order rule: sessions run in order inside a phase. Phase 2 and the first four sessions of Phase 3 do not need the server, so they fill the waiting time. If the server arrives late, do P5-01 to P5-03 on the static site first (they have static variants).

---

## Phase 0 — Foundations

| ID | Session | Tool / model | Acceptance criteria |
|---|---|---|---|
| P0-00 | 👤 Manual setup: GitHub repo, API keys, `.env`, chat Project | you | Repo public on GitHub; OpenAlex key, Semantic Scholar key (requested), contact email for Crossref in `.env`; nothing secret committed |
| P0-01 | Scaffold: uv project, package skeleton, CLI, lint, tests, pre-commit with gitleaks, CI | CC / S | `uv sync && uv run pytest && uv run ruff check .` pass locally and in GitHub Actions; `uv run flatatlas --help` works; `LICENSE` (MIT) and `.env.example` exist |
| P0-02 | Harvest core: settings, profiles, `flatatlas.http` (cache, rate limit, retry, resume, budget guard), DuckDB helpers, run log | CC / S | Unit tests with a mocked server prove: cache hit makes no request; 429 with `Retry-After` is honoured; a killed paged job resumes from the saved cursor; budget guard stops cleanly; no key ever appears in logs |
| P0-03 | Venue registry: `venues.yaml` schema + validation, entries for DCFS, DLT, CIAA verified against DBLP and OpenAlex; ID registry module | CC / S | `flatatlas venues check` validates the file; the three venues have verified DBLP streams, years and predecessors (WIA, DCAGRS) with a note of how each was verified; ID minting is deterministic and tested |
| P0-04 | Web skeleton: SvelteKit + TS static app, `DataSource` interface, fixture data, deploy to GitHub Pages by Actions | CC / S | Public Pages URL shows a home page and one fixture topic page; `npm run check`, `npm run build` pass in CI; deep links work on Pages (SPA fallback) |

**Gate G0:** none (too small). P0-04's PR review doubles as the check.

---

## Phase 1 — Pilot (DCFS, DLT, CIAA)

| ID | Session | Tool / model | Acceptance criteria |
|---|---|---|---|
| P1-01 | DBLP parse from the dump (the API is blocked, D-49): editions, papers, authors with PIDs | CC / S ⏳ | All editions of the three venues in `stg_dblp_*`; paper counts per edition equal DBLP's table of contents (front matter flagged); parser tests on fixtures |
| P1-02 | OpenAlex + Crossref enrichment; **coverage report** | CC / S ⏳ | ≥ 95 % of DBLP papers with a DOI matched in OpenAlex; references, counts by year, affiliations, topics parsed; `reports/coverage-pilot.md` gives abstract/affiliation/reference coverage per venue and decade; daily budget never exceeded |
| P1-03 | Semantic Scholar enrichment + embeddings (S2 vectors, local SPECTER2 fallback) | CC / S ⏳ | Every pilot work has a 768-d vector with its source recorded; local and S2 vectors for a 50-paper sample have mean cosine ≥ 0.9 (or the difference is explained and recorded); abstracts merged by priority into `local_abstract` |
| P1-04 | Entity resolution + core tables + data-quality tests | CC / S | `core_*` tables as in PLAN §4; conference/journal merges produced with confidence; authors anchored on DBLP PIDs; `tests/data_quality` pass; a report lists 30 sampled merges and all uncertain cases |
| P1-05 | Taxonomy tooling: seeds import, reference titles and composite text, phrase mining, clustering, hierarchy candidates, `taxonomy check` (topics and labelled-set schema) | CC / S | `flatatlas taxonomy mine` and `propose` produce a proposal YAML + review document from the pilot corpus, deterministic with a fixed seed; `taxonomy check` rejects cycles, unknown parents, duplicate aliases and a broken `gold.yaml`; reference titles for ≥ 80 % of references, inside the free budget |
| P1-06 | 👤 **Taxonomy v1 + anchors**: Opus drafts `topics.yaml` and `anchors.yaml` from the proposals; you review (2–4 h) | CC / **O** | `taxonomy/topics.yaml` passes `taxonomy check`; 15–25 level-0 topics; every topic has a description, ≥ 3 phrases, ≥ 1 parent or level 0; ≥ 80 anchors, each resolved to a DOI or DBLP key; your review is committed with `reviewed: true` |
| P1-06b | 👤 **Labelled set**: random stratified sample of 400–600 pilot works; Opus drafts level-0 and level-1 labels; you label 50 blind, then review all (2–3 h) | CC / **O** | `taxonomy/gold.yaml` passes `taxonomy check`; two thirds train, one third held-out by hash; sample independent of any tagger output; blind-vs-draft agreement reported; your review is committed |
| P1-07 | Tagger v1 (cascade steps 1–2): per-topic artefacts, signals as per-topic percentiles, shortlist, noisy-or baseline, learned fusion with calibration, provenance | CC / S | `tag_work_topic` filled with calibrated confidence + provenance; shortlist recall ≥ 95 % on gold-train; anchors in corpus ≥ 80 % before propagation; cross-validated numbers on gold-train recorded, held-out untouched; pilot runtime < 10 minutes on the Mac; cost €0 |
| P1-07b | Local decision model (cascade step 3): option-probability scoring with an open model, unsure works only, shuffled options, calibration, cache | CC / S ⏳ | `--limit 50` run measured (seconds per work, memory, order effect) and estimates in PLAN §9.5 and §9.8 replaced; unsure pilot works have `dm_*` signals; tests and CI use a fake scorer; no code path can call a hosted model; cost €0 |
| P1-08 | Propagation + evaluation harness + method comparison on the held-out set + spot-check report | CC / S | All PLAN §9.6 checks implemented; held-out precision/recall at levels 0 and 1 with intervals for noisy-or, top-down and cascade (with and without the decision model), opened once after tuning; adopted method recorded as a decision; hard thresholds met (anchors ≥ 90 %, coverage ≥ 85 %, stability ≥ 95 %) or the misses are explained with a fix list; `reports/eval-*.html` readable in 15 minutes |
| P1-09 | Aggregates, topic edges, map layout, release build, static export | CC / S | Four edge types computed and stored separately; `releases/v…/` with manifest and checksums; `export static` writes the JSON layout of PLAN §11.2 under 30 MB; JSON validated against generated TypeScript types |
| P1-10 | Site: topic, paper, author, venue pages + search | CC / S | The four page types render real pilot data; search finds topics, authors, venues, papers; each tag shows confidence and provenance; Lighthouse accessibility ≥ 90 on topic and paper pages |
| P1-11 | Site: topic map with semantic zoom | CC / S | Home shows 15–25 bubbles sized by volume; click expands children in place; edge-type toggle; ≤ 150 nodes drawn; 60 fps pan/zoom on the M1; list view alternative; no console errors |
| P1-12 | Suggest-a-change issue forms, About/Sources/Methods/Cite pages, polish, public launch of the pilot | CC / S | Each entity page opens a pre-filled GitHub issue; source attributions (including "Semantic Scholar") in the footer; README points to the live site; pilot release tagged `v0.1.0` on GitHub |

**Gate G1 (Opus + you):** full gate of WORKFLOW §5. Extra questions: are the held-out precision and recall good enough to widen, and what floor do we set for later phases? Did the local decision model earn its place? Is D-67 (hosted model, inactive) closed as not needed or put to Guilherme? Does Phase 2 need more abstract sources? Output: go/no-go for widening, tagger fix list, roadmap edits.

---

## Phase 2 — Widen on the laptop

| ID | Session | Tool / model | Acceptance criteria |
|---|---|---|---|
| P2-01 | Remaining core venues by config only (NCMA, AFL, LATA, WORDS, CAI, MCU, RP, UCNC, JALC, IJFCS, RAIRO-ITA + the Tier A additions you approved) | CC / S ⏳ | Venues added with **no code change** outside bug fixes (each fix has a test); venue histories verified and noted; full pipeline re-run; evaluation thresholds still met; taxonomy proposals for new areas generated |
| P2-02 | 👤 Scope rule: implement PLAN §6, tune on hold-out tests, trial on two broad venues (MFCS + Information and Computation) | CC / **O** | `scope_status` for all works; hold-out recall of Tier A ≥ 90 %; background false-positive rate ≤ 5 %; borderline report reviewed by you (20 minutes); thresholds recorded in `config/scope.yaml` and DECISIONS |
| P2-03 | Venue analytics pipeline: all metrics of PLAN §15.1, `venue_facts.yaml` with sources, CORE import | CC / S | `agg_venue_year` and `agg_venue_overlap` filled; each metric has a coverage figure; acceptance rates only where a source URL exists; tests on a fixture venue with hand-computed expected values |
| P2-04 | Venue analytics UI: venue page + compare view + CSV download | CC / S | `/venue/[id]` and `/venues` show all metrics side by side with sources and coverage; no composite score anywhere; compare works for 2–5 venues; charts readable on mobile |

**Gate G2:** data quality across about 20 venues; scope rule behaviour on broad venues; decide the Tier A/Tier B list for the mass import; confirm server sizing with real numbers (bytes per work measured).

---

## Phase 3 — Server stage

| ID | Session | Tool / model | Acceptance criteria |
|---|---|---|---|
| P3-00 | 👤 Manual: request the server (text provided), collect access details | you | Server request sent with the resources of PLAN §14; when granted: hostname, SSH access, open ports confirmed |
| P3-01 | Containerise the pipeline; `compose.yaml`; server profile; images on GHCR | CC / S | `docker compose run pipeline flatatlas run --profile pilot --limit 200` works on the Mac from a clean clone; image built in CI; data root is a mounted volume; no secrets in images |
| P3-02 | PostgreSQL serving schema + loader with versioned schemas and swap | CC / S | `export postgres` loads the pilot release into `atlas_vN`, builds indexes, runs checks, swaps views; loading a second release and rolling back both work; row counts equal the manifest |
| P3-03 | FastAPI read API + search + OpenAPI + tests | CC / S | Endpoints of PLAN §12 (read side) return the same payload shapes as the static JSON; search uses Postgres FTS + trigram; p95 < 200 ms on pilot data locally; API tests in CI against a Postgres service |
| P3-04 | Frontend `ApiDataSource`; full stack locally with Caddy | CC / S | `PUBLIC_DATA_SOURCE=api` build passes the same UI checklist as the static build; `docker compose up` serves the whole site on localhost over HTTPS (local cert) |
| P3-05 | 👤 Deploy to the server: runbook, timers, backups, monitoring summary | CC / S | Public URL serves the site from the server; `docs/runbooks/` has deploy, rollback, restore; weekly refresh timer and nightly backup installed and tested once; restore tested once |

**Gate G3:** security pass (open ports, admin auth, headers, rate limits, secrets), restore drill evidence, load test with a 10× synthetic release, go/no-go for the mass import.

---

## Phase 4 — Mass import

| ID | Session | Tool / model | Acceptance criteria |
|---|---|---|---|
| P4-01 | Bulk loaders + orchestrator: DBLP XML dump parser, large-batch OpenAlex/S2 paths, `flatatlas run` with per-stage state, `flatatlas status` | CC / S | DBLP dump parsed in streaming mode for all configured streams within 4 GB RAM, with incremental refresh; results for the pilot venues unchanged from P1-01; an interrupted `run` resumes at the failed stage; status shows progress and ETA |
| P4-02 | ⏳ Full harvest: all Tier A and Tier B venues, stub collection, two expansion rounds; scope report | CC / S | All configured venues harvested; scope applied; counts per venue and status in `reports/scope-full.md`; raw cache size and API spend recorded; no source blocked us (no sustained 429s) |
| P4-03 | Entity resolution at scale: authors outside DBLP, version merging quality, venue successions | CC / **O** | Merge precision ≥ 95 % on a 100-pair sample judged by Opus with reasons; no two DBLP PIDs merged; provisional authors flagged; uncertain-case report produced |
| P4-04 | 👤 Taxonomy v2 on the full corpus: proposals for new areas (ω-automata, weighted, natural computing, inference, trees/graphs/pictures), your review (2–3 h) | CC / **O** | `topics.yaml` v2 with 400–900 topics, still 15–25 at level 0; reviewed fields untouched unless you changed them; anchors extended to ≥ 150 covering every level-0 topic; `gold.yaml` migrated to v2 and extended to the new venues |
| P4-05 | Tagger v2 on the full field (retrained cascade, local decision model as overnight runs, distilled classifier), incremental mode, scheduled refresh, first full release | CC / **O** ⏳ | comparison on the held-out third recorded and the adoption rule of PLAN §9.6 applied; incremental path runs without the large model; spend €0; `tag --incremental` tags 1,000 new works in < 5 minutes; weekly timer runs end to end; release `v1.0.0` live on the server |

**Gate G4:** full data-quality and tagging gate on the whole field; you read spot checks for your own areas; performance of site and API at full size; decide the feature order of Phase 5.

---

## Phase 5 — Additional features

| ID | Session | Tool / model | Acceptance criteria |
|---|---|---|---|
| P5-01 | Time slider: yearly aggregates, map animation | CC / S | Slider from the first year to today; positions fixed, sizes change; play/pause; topics appear at first activity; smooth on the M1 |
| P5-02 | Bridge papers: scoring, API/static export, "bridges to" UI | CC / S | For any two non-ancestor topics the page lists ranked bridge papers with the reason; the shuffle → synchronization example returns sensible papers (checked by you) |
| P5-03 | Reading paths: survey detection, foundations/core/frontier | CC / S | Each topic with ≥ 30 works has a path with 4 steps and reasons; survey detector precision ≥ 80 % on a 50-item sample judged in the gate |
| P5-04 | Chair tools: reviewer suggestions + COI detection | CC / S | Reviewer list for a topic set with evidence per person; COI matrix with configurable window; only well-resolved authors; limits notice shown |
| P5-05 | Community suggestions backend + moderation queue | CC / S | Suggestion form on every entity page stores to `community`; spam controls; `/admin` queue behind auth; accepting a suggestion writes an override that the next pipeline run applies with provenance `community` |
| P5-06 | 👤 Citable dataset: release automation, Zenodo DOI, how-to-cite | CC / S | A release appears on Zenodo with DOI, licence files, `CITATION.cff`; the site's Cite page shows the DOI and BibTeX; changelog generated from manifests |

**Gate G5:** feature UI checks, privacy and abuse review of suggestions and chair tools, dataset licence check against PLAN §10.

---

## Phase 6 — Historical gaps

| ID | Session | Tool / model | Acceptance criteria |
|---|---|---|---|
| P6-01 | Gap analysis: coverage per venue-year, most-cited missing references, missing-abstract map | CC / S | `reports/gaps.md` ranks gaps by importance (citations from the corpus); a concrete list of venues/years/sources to fill |
| P6-02 | zbMATH Open source: harvest, parse, match, MSC signal, separate CC BY-SA add-on file | CC / S ⏳ | zbMATH records matched to works with confidence; `src_msc` signal available to the tagger; share-alike data kept in its own release file; licence note updated |
| P6-03 | Historical backfill: old venues (SWAT/FOCS, Information and Control, Mathematical Systems Theory, EIK, …) and frequently cited missing works as full records | CC / S ⏳ | Pre-1990 coverage improved and measured against P6-01; pre-1990 anchors all present; taxonomy proposals for historical topics generated |

**Gate G6:** historical data quality, final risk review, maintenance plan (what runs by itself, what needs you, how many hours per month).

---

## After the roadmap
Maintenance mode: weekly automatic refresh, monthly look at `flatatlas status` and the suggestion queue, quarterly release with DOI, yearly taxonomy proposal review.
