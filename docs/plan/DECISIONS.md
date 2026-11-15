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
