# Decisions log

Append only. To change a decision, add a new entry that supersedes it. Format: decision, alternatives, reason.
Entries D-01 to D-04 were confirmed by Guilherme on 2026-11-15. The others were made on his behalf during planning and can be challenged at any gate.

## Confirmed by Guilherme

**D-01 Name and place.** Repo `flat-atlas` in `~/Documents/work/formal-lang/flat-atlas`; Python package `flatatlas`; site title "The FLAT Atlas".

**D-02 Taxonomy gets a one-time human review.** The pipeline proposes the topic DAG; Guilherme reviews it once (2–4 hours) and small proposals later. Paper tagging stays fully automatic. *Alternative:* fully automatic DAG. *Reason:* a few hours of expert time fix the errors that would otherwise spread into every tag.

**D-03 Frontend freedom.** Guilherme is comfortable with JavaScript/TypeScript, so a modern framework is acceptable.

**D-04 Server expected within about 6 months.** The static pilot only needs to handle a subset; the full field waits for the server. A fallback exists (RISKS R7).

## Architecture

**D-05 The pipeline always computes in DuckDB + Parquet; PostgreSQL is a serving copy loaded from a release.** *Alternatives:* SQLite for the pilot then a port to Postgres; Postgres everywhere including the laptop. *Reason:* one code path in both stages; DuckDB handles the full field (hundreds of thousands of works, millions of citation edges) on one machine; no ORM or dual SQL dialect; the migration to the server becomes "load a release".

**D-06 A versioned release (Parquet + manifest) is the contract** between pipeline, static site, server database and Zenodo. *Reason:* the site shows exactly what the dataset contains; rollbacks are trivial.

**D-07 Core journals that publish much non-FLAT material are Tier B.** Information and Computation, Acta Informatica, Fundamenta Informaticae and Natural Computing are filtered by the scope rule with a lenient threshold; they are not included wholesale. *Alternative:* include everything from the core list. *Reason:* "comes from automata and formal languages" would be diluted by unrelated logic, complexity and evolutionary-computing papers. **Needs confirmation** (OPEN-QUESTIONS Q3).

**D-08 Stack for the pipeline.** Python 3.12 (pinned; the system Python 3.15 is too new for the ML wheels), uv, Typer, pydantic, httpx, DuckDB, pyarrow, rapidfuzz; ruff, pytest, pre-commit, gitleaks, GitHub Actions. *Alternatives:* Poetry/conda; pandas-centred code; Snakemake/Prefect/Dagster for orchestration. *Reason:* uv gives a fast, locked, reproducible environment; a small hand-written stage runner is enough for a linear pipeline and has no service to maintain.

**D-09 Frontend: SvelteKit + TypeScript with the static adapter; Sigma.js v3 + graphology for the map; MiniSearch for pilot search; Observable Plot for charts.** *Alternatives:* Astro (excellent for content sites, weaker for an app-like map with shared state); Next.js/React (heavier, more boilerplate, static export has more limits); plain Vite + vanilla (less structure); D3 canvas or Cosmograph or deck.gl for the map. *Reason:* small bundles, simple state for map + slider, static output for Pages and the same app in API mode. Sigma is kept behind one component because, with a precomputed layout and at most about 150 visible nodes, the renderer is replaceable.

**D-10 Map layout is precomputed in the pipeline, not in the browser.** *Alternative:* live force simulation. *Reason:* deterministic and stable across visits and across the time slider; cheap on phones; avoids the hairball because the pipeline controls aggregation.

**D-11 Client-rendered entity pages with a static fallback (SPA mode); only topic and venue pages are prerendered.** *Alternative:* prerender every paper page. *Reason:* hundreds of thousands of HTML files do not fit GitHub Pages (1 GB) or sensible build times.

**D-12 Server stack: Docker Compose, PostgreSQL + pgvector, FastAPI with plain SQL, Caddy.** *Alternatives:* Kubernetes (overkill); Django (admin for free, but a heavier app and ORM); nginx + certbot (more to configure). *Reason:* smallest number of moving parts a single maintainer can restore from a runbook.

**D-13 No workflow engine, no vector database, no message queue.** Numpy/DuckDB for similarity at this scale; pgvector only if "similar papers" is offered.

## Data

**D-14 Abstracts are stored locally for tagging and never redistributed** (site or dataset). Embeddings may be released as a separate optional file. *Alternative:* show OpenAlex abstracts (CC0 inverted index). *Reason:* publisher rights on abstracts are contested; links to DOI/OpenAlex serve users equally well. Can be revisited (OPEN-QUESTIONS Q4).

**D-15 Licences: code MIT; data releases CC BY 4.0 with source attributions; zbMATH-derived fields in a separate CC BY-SA file; CORE ranks shown on the site but not redistributed.** *Alternatives:* CC0 for data (conflicts with ODC-BY attribution from Semantic Scholar); ODbL (share-alike discourages reuse). Not legal advice; see RISKS R3.

**D-16 DBLP defines venue membership and author identity; other sources enrich by DOI.** *Reason:* OpenAlex files LNCS papers under the book series; DBLP's author disambiguation is the best open one for this community.

**D-17 The pilot and the mass import use APIs; bulk snapshots are optional optimisations.** *Reason:* verified pricing and limits make the whole field affordable on free tiers (about 3,000 OpenAlex list calls); the laptop has 22 GB free; the OpenAlex snapshot is 745 GB.

**D-18 Stable opaque IDs with a registry and redirects.** *Alternative:* use DBLP keys or DOIs as primary keys. *Reason:* works have several versions and some have no DOI or DBLP key; public URLs must survive merges.

**D-19 Uncertain merges are not made.** Version and author merges below the threshold stay separate and are listed for review/community suggestions. *Reason:* a wrong merge is harder to notice and undo than a duplicate.

## Scope, taxonomy, tagging

**D-20 Inclusion rule = venue tiers + a multi-signal scope score + field guards + at most two expansion rounds** (PLAN §6), tuned by automatic hold-out and background tests. *Alternatives:* venue lists only (misses FLAT papers in TCS/JCSS and older journals); keywords only (floods from verification and combinatorics); citation proximity only (drifts).

**D-21 The topic DAG lives in git as YAML (`taxonomy/topics.yaml`); the pipeline only proposes changes.** *Reason:* reviewable diffs, community suggestions as pull requests, no silent taxonomy drift.

**D-22 Own topic names and descriptions; CCS and MSC appear only as cross-reference codes.** *Reason:* MSC2020 is CC BY-NC-SA and CCS is ACM copyright.

**D-23 SPECTER2 is the paper embedding** (precomputed vectors from Semantic Scholar where available, the same public model locally otherwise). *Alternatives:* general sentence-transformers models (better for short queries, worse for paper–paper similarity), SciNCL, newer long-context encoders. *Reason:* free precomputed vectors for most works and identical geometry locally. A small general model may be added for topic-description matching if the P1-07 experiment favours it.

**D-24 Tagger v1 is a transparent weighted fusion; v2 (weak supervision) is adopted only if it wins on the automatic checks.** *Reason:* explainable provenance first; learned weights only with evidence.

**D-25 Propagation runs exactly one extra pass.** *Alternative:* iterate to convergence. *Reason:* deterministic, incremental-friendly, avoids over-smoothing topics along citation chains.

**D-26 The local LLM is off by default and never an override.** Its output is one more signal for low-confidence works only. *Reason:* zero-cost and reproducibility constraints; no acceptance criterion depends on it.

**D-27 Evaluation uses anchor papers, agreement, coherence, venue sanity, stability and spot-check reading**, never a hand-labelled test set. Anchors are drafted by Fable, verified against real identifiers, and reviewed together with the taxonomy.

## Features

**D-28 No composite venue score, no ranking of venues or people.** Metrics appear side by side with source and coverage. Acceptance rates only with a cited source, never estimated.

**D-29 Chair tools show only well-resolved authors (confidence ≥ 0.8) and store no user input.**

**D-30 Suggestions without accounts:** GitHub issue forms in the pilot; a database table and one admin login in the server stage. Accepted suggestions become overrides applied by the pipeline with provenance `community`.

## Method

**D-31 One session = one prompt file = one branch = one PR**, with CI and a human-read diff. Sonnet by default; Fable for 5 design sessions, all gates, re-planning and stubborn bugs.

**D-32 Long jobs are launched by Guilherme outside Claude sessions.**

**D-33 Phase 3 starts on the Mac with containers**, so the server stage is built and tested before the server exists.

**D-34 Pilot venue order kept as requested (DCFS, DLT, CIAA)** despite expected poor abstract coverage (all three are Springer LNCS). *Reason:* it tests the hardest realistic case for the tagger early; the gate G1 question is exactly whether titles + citations + embeddings suffice.

## Answers to open questions (confirmed by Guilherme, 2026-11-15)

**D-35 Models: Sonnet 5.5 by default, Opus 5.5 where the plan says Fable.** Supersedes the model part of D-31. Fable is no longer available on Guilherme's plan, so the design sessions, gates, re-planning and stubborn bugs go to Opus. `WORKFLOW.md`, `ROADMAP.md`, `PLAN.md` and the session prompts were updated in the P0-01 PR; older entries in this log and in `PROGRESS.md` keep the name as history.

**D-36 The broad core journals are harvested wholesale and filtered after tagging.** Supersedes D-07. Information and Computation, Acta Informatica, Fundamenta Informaticae and Natural Computing are not filtered by the scope rule up front; all their publications are considered, and those that turn out not to belong to FLAT after tagging are dropped. *Reason (Guilherme):* do not lose FLAT papers to an early filter. The mechanism (how "does not belong after tagging" is decided, with confidence and provenance) is designed in P2-01 / P2-02; PLAN §6 and §7 need the matching edit then.

**D-37 Abstracts are shown on the site wherever there is no legal issue.** Supersedes the "never shown" part of D-14. Which sources and licences qualify (for example OpenAlex CC0 abstracts) is settled in P1-10 with RISKS R3 in mind; until then nothing is exported. Redistribution in the dataset stays off unless decided separately.

## Scaffold (P0-01)

**D-38 Packaging and tooling details.** `src/` layout built with hatchling; `requires-python = ">=3.12,<3.13"`; dev tools in a PEP 735 `dev` dependency group (installed by plain `uv sync`). pre-commit is not a project dependency: it runs with `uvx pre-commit`. ruff rules `E, F, W, I, UP, B, SIM`, line length 100. CI runs gitleaks from the official container, pinned to the same version as the pre-commit hook, over the full history. *Alternatives:* setuptools or the uv build backend; `gitleaks-action` (scans only the pushed commits). *Reason:* fewest moving parts, and "nothing in the full history" is checked on every run.

## Harvest core (P0-02)

**D-39 The HTTP cache stores gzip JSON per request under `data/raw/<source>/<hash[:2]>/`.** Each entry is `<hash>.json.gz` plus `<hash>.meta.json` (status, sanitised URL, `fetched_at`, rate-limit headers). The key hashes method, URL, sorted params and body, and **excludes** the API key and the contact email, so rotating a key never invalidates the cache and no key can reach disk. Data is written first and metadata last; a crash in between is just a cache miss. A 404 or 410 is cached as a result (`data: null`) so missing DOIs are not asked again; any other 4xx raises. *Alternative:* store raw bytes (needed if a source returns XML; revisit with zbMATH OAI-PMH in P6-02).

**D-40 The daily budget lives in a JSON ledger, not in DuckDB.** `data/raw/<source>/_budget.json` maps UTC day to spent micro-dollars. *Reason:* `http.py` stays independent of the warehouse, and a running harvest holds the DuckDB write lock. This avoids a new table, so PLAN §4.6 is unchanged. Every real attempt is charged, retries included (conservative); cache hits and free call kinds cost nothing. A call that would exceed the budget raises `BudgetExhausted` before it is sent.

**D-41 Retry and rate-limit policy.** Hand-written, with injectable clock and sleep so tests never wait (`tenacity` is a dependency from P0-01 but is not used). Retry on 429, 500, 502, 503, 504 and transport errors, at most `max_attempts` (6) with back-off 1, 2, 4, 8, 16 s; a `Retry-After` (seconds or HTTP date) replaces the back-off. A `Retry-After` above `max_retry_wait_seconds` (300) is refused rather than slept through, so the job stops and can be relaunched. Crossref's `x-rate-limit-limit` and `x-rate-limit-interval` can lower the rate, never raise it. The client is synchronous; the profile's `concurrency` is not used yet.

**D-42 Secrets never reach logs or errors.** Keys go on the wire only (query parameter or header, per `auth` in `config/sources.yaml`); they are not in the cache key, cache files, error messages or logged URLs. Errors raised from transport failures are re-raised without the original exception (`from None`), because httpx messages can echo the URL. The `httpx` and `httpcore` loggers are forced to WARNING (httpx logs request URLs at INFO). Registered secrets are also replaced by `***` by the log formatter. OpenAlex key parameter name `api_key` is unverified.

**D-43 Profiles and source table.** `config/sources.yaml` holds per-source `requests_per_second`, `burst`, `batch_size`, `daily_budget_usd`, `costs`, `auth` and `mailto_param`; `config/profiles/<name>.yaml` follows PLAN §5.4. Data root precedence: `--data-root` argument, `FLATATLAS_DATA_ROOT`, profile; relative paths are relative to the repository root. `server.yaml` values are placeholders until P3-00; `active_venues: all` means every venue in `config/venues.yaml`. Semantic Scholar `batch_size` starts at 100, not the 500 PLAN recalls (unverified).

**D-44 `paged()` is at-least-once.** The cursor of page N+1 is stored when the consumer asks for it, after finishing page N. A kill during page N repeats page N on resume (free, because it is cached), never skips it. Job states: `running`, `interrupted`, `done`; a `done` job yields nothing unless `restart=True`.

**D-45 `flatatlas status` is a plain command, not a group.** `COMMAND_GROUPS` keeps all 13 names; `PLAIN_COMMANDS` lists those that are commands. Status opens the warehouse read-only and says so if a running job holds the write lock.
