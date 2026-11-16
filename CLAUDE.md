# The FLAT Atlas — instructions for Claude sessions

## What this is
An open, public map of formal languages and automata theory (FLAT), 1950s to today.
It links **topics, papers, authors and venues**. Solo maintainer (Guilherme), zero budget, public repo.

**Current state:** see `docs/plan/PROGRESS.md` (the single source of truth for "where are we").

## Where things live
| What | Where |
|---|---|
| Architecture, data model, tagging method | `docs/plan/PLAN.md` |
| Phases, sessions, acceptance criteria | `docs/plan/ROADMAP.md` |
| Ready-to-paste session prompts | `docs/plan/sessions/` |
| How Guilherme works with Claude tools | `docs/plan/WORKFLOW.md` |
| Decisions already made (do not re-litigate) | `docs/plan/DECISIONS.md` |
| Risks and open questions | `docs/plan/RISKS.md`, `docs/plan/OPEN-QUESTIONS.md` |
| Progress log and hand-off notes | `docs/plan/PROGRESS.md` |
| Notes brought in from Claude chat or reading | `docs/notes/` |
| Venue list, source settings, profiles | `config/` |
| Topic DAG (human-reviewed), anchors, labelled set (`gold.yaml`) | `taxonomy/` |
| Pipeline code (Python package `flatatlas`) | `src/flatatlas/` |
| Tests | `tests/` |
| Static site / frontend (SvelteKit) | `web/` |
| Read API (server stage, FastAPI) | `api/` |
| Local data, caches (never committed) | `data/` |

## Stack (decided; see DECISIONS.md)
- Python 3.12 managed by **uv**; CLI `flatatlas` (Typer); pydantic models; httpx.
- Storage: raw API responses cached on disk as gzip JSON; warehouse in **DuckDB + Parquet**.
  The pipeline always computes in DuckDB. PostgreSQL (server stage) is a *serving* database loaded from an exported release.
- Embeddings: SPECTER2 (from Semantic Scholar when available, computed locally otherwise).
- Frontend: SvelteKit + TypeScript, static adapter; map with Sigma.js v3 + graphology; layout precomputed in the pipeline.
- Server stage: Docker Compose, PostgreSQL + pgvector, FastAPI, Caddy.
- Quality: ruff, pytest, pre-commit with gitleaks, GitHub Actions CI.

## Hard rules
1. **No secrets in the repo.** Keys live in `.env` (git-ignored). Only `.env.example` is committed. Never print keys.
2. **Metadata and links only.** Never download or store full texts. Abstracts are used locally for tagging and are **not** exported to the site or dataset unless `DECISIONS.md` says otherwise.
3. **Zero running cost.** No paid APIs, no paid services.
4. **Every automatic assignment** (tag, merge, scope decision, edge) stores a `confidence` and a `provenance` (method + version).
5. **Never hand-edit generated data.** Fix the code or the config and re-run. The only human-edited data files are in `config/` and `taxonomy/`.
6. **Never overwrite human-reviewed taxonomy fields** (`reviewed: true`). Write proposals to `taxonomy/proposals/`.
7. **Long jobs run outside Claude sessions.** Harvests and embedding runs are scripts Guilherme launches (`flatatlas ... ` in a terminal or tmux). Claude writes them, tests them on a tiny sample (`--limit`), and reads their logs. Do not sit and wait on a long job.
8. **Be polite to the sources.** All HTTP goes through `flatatlas.http` (cache, rate limit, retry, resume). Never call a source API directly with ad-hoc code.
9. **Adding a venue is a config change** (`config/venues.yaml`), never a code change.
10. **Stay in scope of the session prompt.** Ideas outside it go to `docs/plan/PROGRESS.md` under "Parking lot", not into code.

## Conventions
- Branch per session: `s/<session-id>-<slug>` (e.g. `s/P1-02-openalex`). Small commits. Open a PR to `main`; CI must pass before merge.
- Every data transform has a test with a small fixture in `tests/fixtures/` (real cached responses, trimmed).
- Each pipeline stage is a pure "inputs → outputs" step, idempotent and resumable, registered in the CLI.
- Tables and columns follow `PLAN.md` §4. Schema changes need a `DECISIONS.md` entry.
- British or American spelling: keep the spelling already used in the file you edit.
- Commands (once Phase 0 is done): `uv sync`, `uv run pytest`, `uv run ruff check .`, `uv run flatatlas --help`, `cd web && npm run dev`.

## How every session starts
1. Read this file, `docs/plan/PROGRESS.md` (top section and last hand-off), and the session prompt.
2. Read only the plan sections the prompt lists. Do not read the whole plan.
3. Use plan mode: propose the steps and the files you will touch. Wait for approval.

## How every session ends
1. Run tests and lint. Report failures honestly; do not mark work done if a check fails.
2. Update `docs/plan/PROGRESS.md`: tick the session, add a dated entry (what was built, what was not, surprises) and a **hand-off note** for the next session.
3. Record any decision made in `docs/plan/DECISIONS.md`.
4. Commit, push the branch, open the PR. Do not merge without Guilherme's OK.
