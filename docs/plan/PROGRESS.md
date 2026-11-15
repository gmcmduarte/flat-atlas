# Progress

## Current state (keep this section under 30 lines)
- **Phase:** 0 (not started)
- **Last merged session:** none (planning session of 2026-11-15 created the plan)
- **Next:** `sessions/P0-00-manual-setup.md` (Guilherme), then `P0-01`
- **Live site:** none yet
- **Latest release:** none
- **Known problems:** none
- **Waiting on Guilherme:** answers in `OPEN-QUESTIONS.md` (Q1, Q2, Q6 before P0-01; the rest later)

## Checklist
**Phase 0** — [ ] P0-00 · [ ] P0-01 · [ ] P0-02 · [ ] P0-03 · [ ] P0-04
**Phase 1** — [ ] P1-01 · [ ] P1-02 · [ ] P1-03 · [ ] P1-04 · [ ] P1-05 · [ ] P1-06 · [ ] P1-07 · [ ] P1-08 · [ ] P1-09 · [ ] P1-10 · [ ] P1-11 · [ ] P1-12 · [ ] G1
**Phase 2** — [ ] P2-01 · [ ] P2-02 · [ ] P2-03 · [ ] P2-04 · [ ] G2
**Phase 3** — [ ] P3-00 · [ ] P3-01 · [ ] P3-02 · [ ] P3-03 · [ ] P3-04 · [ ] P3-05 · [ ] G3
**Phase 4** — [ ] P4-01 · [ ] P4-02 · [ ] P4-03 · [ ] P4-04 · [ ] P4-05 · [ ] G4
**Phase 5** — [ ] P5-01 · [ ] P5-02 · [ ] P5-03 · [ ] P5-04 · [ ] P5-05 · [ ] P5-06 · [ ] G5
**Phase 6** — [ ] P6-01 · [ ] P6-02 · [ ] P6-03 · [ ] G6

## Log (newest first)

### 2026-11-15 — Planning session (Fable)
- **Built:** `CLAUDE.md`, `README.md`, `.gitignore`, and under `docs/plan/`: `PLAN.md`, `WORKFLOW.md`, `ROADMAP.md`, `DECISIONS.md`, `RISKS.md`, `OPEN-QUESTIONS.md`, `sessions/` (39 prompts, 2 manual checklists, gate template).
- **Not built:** no code, no GitHub remote, no CI.
- **Surprises:** OpenAlex now needs a free API key with a $1/day budget (enough for the whole field); abstracts for Springer LNCS venues are likely to be scarce; the CORE portal blocks automated access; the Mac has only 22 GB of free disk.
- **Hand-off to P0-00 / P0-01:** nothing exists except documents. P0-01 creates the Python project from scratch. Python must be pinned to 3.12 (the system has 3.15). `uv`, `git`, `gh`, `node`, `docker` are installed; `ollama` and `tmux` are not.

## Parking lot (ideas outside the current session; do not build)
- "Similar papers" on paper pages using embeddings (needs pgvector; server stage).
- Per-author topic timeline visualisation.
- Wikidata / ROR enrichment for institutions.
- A short dataset paper describing the Atlas.
