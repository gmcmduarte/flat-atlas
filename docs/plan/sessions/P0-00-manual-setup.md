# P0-00 — Manual setup (Guilherme, about 30 minutes)

Not a model session. Do these yourself; tick them in `PROGRESS.md`.

## GitHub
- [ ] Create the public repository `flat-atlas` under your account (no README, no licence: the repo already has them).
- [ ] In this folder: `git remote add origin git@github.com:<you>/flat-atlas.git` then `git push -u origin main`.
- [ ] Settings → Branches: protect `main` (require a pull request and passing checks; allow yourself to merge).
- [ ] Settings → Code security: turn on secret scanning and push protection.
- [ ] Settings → Pages: source "GitHub Actions" (needed in P0-04).

## API access (all free)
- [ ] **OpenAlex:** create an account at openalex.org and copy the free API key.
- [ ] **Semantic Scholar:** request an API key with the form at semanticscholar.org/product/api (approval can take days; the pilot can start without it, slowly).
- [ ] **Crossref:** no key. Decide which email address goes in the `mailto` parameter. Use an address you are happy to expose to Crossref and DBLP (for example a university address), not a private one.
- [ ] Create `.env` in the repo root (it is git-ignored) once P0-01 has added `.env.example`:
  ```
  OPENALEX_API_KEY=...
  S2_API_KEY=...
  CONTACT_EMAIL=...
  FLATATLAS_PROFILE=pilot
  FLATATLAS_DATA_ROOT=./data
  ```
  Never paste these values into a Claude session or chat.

## Mac
- [ ] Free disk space: you have about 22 GB free. The pilot needs under 5 GB; Phase 2 up to about 12 GB; Docker images in Phase 3 another 5–10 GB. Free some space or point `FLATATLAS_DATA_ROOT` at an external disk.
- [ ] `uv`, `git`, `gh`, `node` and `docker` are already installed. Run `gh auth status` to confirm GitHub login.
- [ ] Install tmux (`brew install tmux`) for long jobs.

## Claude
- [ ] In claude.ai create a Project "FLAT Atlas" and add `CLAUDE.md`, `docs/plan/PLAN.md`, `docs/plan/DECISIONS.md` as project knowledge.
- [ ] In Claude Code, check which models your plan offers (`/model`) and how much Fable usage you have (`/usage`). Note it in `docs/notes/claude-plan.md`.

## Decisions to give before P0-03 / P2-01
- [ ] Read `docs/plan/OPEN-QUESTIONS.md` and write your answers in it.
