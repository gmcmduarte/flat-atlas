# Working method

How Guilherme builds The FLAT Atlas with Claude's tools. Tool facts were checked against the Claude Code documentation on 2026-11-15 (`code.claude.com/docs`). Tools change fast: when something here does not match what you see, trust the tool and fix this file.

---

## Cheat sheet (one page)

| I want to… | Tool | Model | Start like this |
|---|---|---|---|
| Run the next build session | Claude Code (desktop app Code tab, or terminal `claude`) in the repo | as the session file says (mostly Sonnet) | New session → paste the whole file `docs/plan/sessions/<id>.md` |
| Review a session's diff before merging | VS Code with the Claude Code extension, or the desktop app's diff view | none needed, or Sonnet for questions | Open the PR branch; read the diff; ask "explain this change" on selected code |
| Fix a small bug or tweak I can see | VS Code extension | Sonnet | Select the code, `@`-mention the file, describe the fix |
| Debug something Sonnet failed at twice | Claude Code | **Opus** | "Read PROGRESS.md hand-off. Sonnet tried X and Y. Find the root cause before changing code." |
| Review a finished phase | Claude Code, **fresh session** | **Opus** | Paste `docs/plan/sessions/GATE.md` with the phase number |
| Re-plan after a gate or a surprise | Claude Code, plan mode | **Opus** | "Read ROADMAP.md, PROGRESS.md, RISKS.md. Propose changes to the roadmap. Do not edit code." |
| Design work: taxonomy, tagging, scope rule | Claude Code | **Opus** | the Opus-marked session files |
| Brainstorm, ask a FLAT or tooling question | Claude chat | Sonnet (Opus for hard ones) | In the "FLAT Atlas" chat project |
| Read a paper, preface or API doc and extract facts | Claude chat (upload the PDF or paste the link) | Sonnet | "Extract … as a table. Mark what is not stated." Then save to `docs/notes/` |
| Draft text for the site (About, Methods, How to cite) | Claude chat | Sonnet | Paste the relevant PLAN section; ask for a draft; save to `docs/notes/drafts/` |
| Collect acceptance rates from prefaces | Claude chat | Sonnet | Upload preface → "submissions, accepted, quote the sentence" → paste into `config/venue_facts.yaml` through a Code session |
| Launch a harvest or embedding run | **My own terminal** (tmux), not Claude | — | `uv run flatatlas harvest … 2>&1 \| tee data/logs/<name>.log` |
| Check on a running or finished job | Claude Code | Sonnet | "Read the last 200 lines of data/logs/<name>.log and `ops_harvest_state`. Is it healthy?" |
| Check the site in a browser | Claude Code desktop (built-in browser preview) | Sonnet | "Start the web dev server and check /topic/shuffle-of-words against the acceptance list" |
| Do something away from my desk | Claude Code on the web / mobile app, or Remote Control of a local session | Sonnet | Only for reading, reviewing PRs and small doc changes; not for data runs |
| Capture an idea that is out of scope | any | — | Add one line to "Parking lot" in `PROGRESS.md`. Do not build it. |

---

## 1. Which tool for which job

**Claude chat (claude.ai web, desktop, mobile)** — thinking and reading, no repo access.
- Use it for: brainstorming; "is this a sensible topic split?"; reading PDFs (prefaces, surveys, API terms); drafting site text; quick questions on the phone.
- Create one chat **Project** called "FLAT Atlas" and add `CLAUDE.md`, `PLAN.md` and `DECISIONS.md` as project knowledge. Refresh them after each gate.
- Rule: if the answer must end up in the repo, it goes through `docs/notes/` (§7). Chat never is the place where a decision lives.

**Claude Code (desktop app Code tab or terminal)** — all building.
- Use it for: every build session, multi-file changes, running the pipeline on small samples, tests, git, PRs, reading logs.
- Desktop app when you want visual diffs, several sessions side by side and the built-in browser to check the site. Terminal when you are already in tmux next to a running job. Both read the same `CLAUDE.md`, settings and skills.
- Rule: one session = one session file = one branch = one PR.

**Claude Code in VS Code (the extension)** — reviewing and editing alongside Claude.
- Use it for: reading a PR diff with inline diffs; small targeted edits; taxonomy YAML editing (you edit, Claude checks with `flatatlas taxonomy check`); frontend tweaks while the dev server runs.
- Rule: if you expect to read or touch the code yourself during the work, use VS Code. If you expect to delegate and review at the end, use the desktop app or terminal.

**Claude Code on the web / mobile** — optional. Good for reviewing a PR or asking Claude to fix a failing CI check when you are away. Cloud sessions do not have your `data/` folder, so nothing that needs the warehouse.

**Not used for now:** agent teams, dynamic workflows, scheduled cloud tasks, GitHub code-review automation. They cost usage and add moving parts. Revisit at the Phase 3 gate.

---

## 2. Which model for which job

Default: **Sonnet**. Switch to **Opus** only for the cases below. In Claude Code switch with `/model`; the session files state the model on their first line.

| Use Opus for | Why |
|---|---|
| Sessions marked Opus in the roadmap: taxonomy draft (P1-06, P4-04), scope rule tuning (P2-02), entity-resolution at scale (P4-03), tagger v2 (P4-05) | judgment and domain knowledge decide the quality |
| Every gate review (G1–G6) | a second, stronger and *fresh* pair of eyes |
| Re-planning the roadmap | consequences across the whole plan |
| A bug Sonnet failed to fix in two attempts | stop paying for retries |
| Reviewing a diff that touches the schema, IDs or merge logic | mistakes here are expensive to undo |

| Use Sonnet for | Why |
|---|---|
| All other build sessions (34 of 39) | the session files are specific enough |
| Tests, refactors, CI fixes, docs, frontend components | routine |
| Reading logs, monitoring jobs, small questions | cheap |

Keeping usage reasonable:
- Opus sessions are short and focused: they read the plan and reports, decide, and write specs or YAML. Let Sonnet do the typing that follows.
- Never keep an Opus session open "to continue later". End it with a hand-off; start Sonnet fresh.
- Use Claude chat with Sonnet for questions that do not need the repo.
- Check `/usage` (or the usage panel) before starting an Opus gate; a gate needs a clear block of usage. ⚠ Exact plan limits for Opus were not verified; if Opus is scarce on your plan, do gates with Sonnet at high effort and reserve Opus for P1-06 and G1.
- If a session file says Sonnet and Sonnet struggles on the *plan* (not the typing), stop, switch to Opus for the plan only (`/model`, plan mode), then switch back.

---

## 3. The session loop

**Before (2 minutes, you).** `git switch main && git pull`. Check `PROGRESS.md` says the previous session is merged. Pick the next session file.

**Start.** New Claude Code session in the repo → set the model → paste the session file. Each file tells Claude to read `CLAUDE.md`, the top of `PROGRESS.md` and named plan sections, then to **plan first** (plan mode, Shift+Tab, or "plan before coding").

**Checkpoint 1: the plan.** Read Claude's plan. Check three things: it touches only the files the session expects; it has a test for every data transform; it does not start long jobs. Approve or correct.

**Build.** Claude works on branch `s/<id>-<slug>` with small commits. Let it run; do not micro-manage.

**Checkpoint 2: evidence.** Before accepting "done", ask for: test output, the acceptance-criteria list with pass/fail for each line, and for data sessions a small sample of real output (10 rows) that you look at yourself.

**Long job, if the session needs real data.** Claude gives you the exact command. You run it in your terminal. When it finishes, tell Claude; it reads the log and the state tables (§6).

**End.** Claude updates `PROGRESS.md` (tick, dated entry, hand-off note, parking lot), `DECISIONS.md` if needed, pushes, opens a PR.

**Review and merge (you, 10–20 minutes).** Open the PR in VS Code or the desktop diff view. Read the whole diff if it is under about 400 lines; if larger, ask a fresh Sonnet session for `/code-review` on the branch and read the summary plus the files that touch schema, IDs, merging or scoring. CI green → squash-merge → delete the branch.

**PRs as a solo maintainer: yes.** They give CI a place to run, a diff to read, and a history that maps one-to-one to sessions.

**When to stop a session early.** The same error three times; the plan changing under your feet; Claude proposing schema changes not in the session file; context getting long (§4). Ask for a hand-off note, end the session, start fresh.

---

## 4. Keeping context across sessions

| File | Holds | Size rule |
|---|---|---|
| `CLAUDE.md` | what the project is, stack, hard rules, conventions, where things are, start/end protocol | under 200 lines; loaded every session, so every line costs |
| `docs/plan/PLAN.md` | the design; changes only through a decision | sessions read named sections only |
| `docs/plan/ROADMAP.md` | phases, sessions, acceptance criteria | |
| `docs/plan/PROGRESS.md` | **current state** on top (phase, last merged session, next session, known problems), then the session checklist, then dated log entries with hand-off notes, then the parking lot | keep the top section under 30 lines; older log entries move to `docs/plan/archive/` at each gate |
| `docs/plan/DECISIONS.md` | numbered decisions with reasons | append only; supersede, do not rewrite |
| `docs/notes/` | knowledge from chat, reading, experiments (§7) | one topic per file |
| `docs/runbooks/` | how to run a harvest, restore the server, cut a release | written in the sessions that create the procedures |
| `.claude/skills/` | repeatable procedures once they have been typed twice (for example `/session-end`, `/check-job`) | add from Phase 1 on, not before |
| `.claude/rules/` | path-scoped rules (for example frontend conventions that load only under `web/`) | when `CLAUDE.md` grows past its limit |

Auto memory: Claude Code also keeps its own memory per project. Treat it as a convenience. Anything a future session *must* know goes into the files above, which are in git.

**Avoiding context overload**
- One session file per session. If the work turns out bigger, split and start a new session; do not push on.
- Start fresh after every merged PR, after every long job, and whenever the topic changes.
- Use `/clear` between unrelated tasks; use `/compact` only as a last resort inside a session you cannot split.
- Ask Claude to use a **subagent** for wide reading that only needs a conclusion: "use a subagent to find where X is used", exploring a library's docs, reading a long log, reviewing a diff. The main session receives the summary only.
- Do not paste large data into the session. Point Claude at a file and ask it to query with DuckDB and show 10 rows.
- Sessions read `PROGRESS.md` top + last hand-off only, never the full log.

---

## 5. Quality gates

A phase is done when a **separate, fresh Opus session** has run `docs/plan/sessions/GATE.md` for that phase and written `docs/plan/reviews/G<n>-review.md` with a verdict: *pass*, *pass with fixes* (listed as small follow-up sessions), or *fail* (re-plan).

The gate checks, in this order:
1. **Acceptance criteria** of every session in the phase, re-verified by running the checks, not by reading the log.
2. **Data quality** (from `flatatlas evaluate` and `tests/data_quality/`): row counts per venue-year against DBLP's own counts; duplicate DOIs; orphan authorships; works without year or venue; share of works matched in each source; merge-confidence histogram; a random sample of 30 merges read by Opus and judged.
3. **Tagging**: all §9.6 thresholds; Opus reads the spot-check report for 10 topics chosen across levels and writes down concrete errors and their likely cause (dictionary, centroid, taxonomy).
4. **UI** (from Phase 1 on): Opus drives the built-in browser through a fixed checklist: search for three topics, open topic → child → related topic → bridge, open a paper and an author, expand map bubbles, check an empty state, check a narrow (mobile) viewport, check that every page shows sources and a "Suggest a change" link. Console must be free of errors.
5. **Code health**: CI green, tests exist for every transform, no secrets (`gitleaks` on full history), README and runbooks match reality.
6. **Plan check**: are RISKS and the next phase's sessions still right? Opus proposes edits to ROADMAP and session files.

Your part of a gate (30–60 minutes): read the review, look at the spot-check report yourself for the topics you know best (this is the cheapest expert check in the whole project), decide.

---

## 6. Long-running jobs

Rule: **Claude writes and checks jobs; you launch them; nobody babysits.**

- Every long job is a `flatatlas` command that is resumable, logs progress every N items with an ETA, writes state to `ops_harvest_state`, and exits non-zero on failure.
- In a session, Claude runs the job with `--limit 50` to prove it works, then gives you the full command.
- You launch in tmux (or a terminal tab): `uv run flatatlas harvest openalex --profile pilot 2>&1 | tee data/logs/$(date +%F)-openalex.log`. On the Mac, prefix with `caffeinate -i` so it does not sleep.
- OpenAlex jobs stop by themselves at the daily budget; relaunch the same command the next day and it resumes.
- To check: new or existing Claude session → "read the tail of the log and the state table; report progress, errors, and whether to relaunch". Or run `uv run flatatlas status` yourself.
- On the server, the same commands run under systemd timers; failures write to a log that `flatatlas status` summarises. Optionally ask Claude Code to check that summary on a schedule later (desktop scheduled tasks); not needed at the start.
- Typical durations (estimates): pilot DBLP + OpenAlex + S2 harvest: minutes to an hour; pilot embeddings for works missing from S2: minutes; full-field harvest on the server: a few days of elapsed time, mostly waiting on the 1 request/s Semantic Scholar limit and daily budgets.

---

## 7. Bringing results back from Claude chat

- Anything worth keeping becomes a file in `docs/notes/` named `YYYY-MM-DD-topic.md` with a three-line header: **source** (chat link or document), **question**, **status** (`raw` / `checked` / `adopted in <file>`).
- Ask chat to produce the note itself: "Summarise what we decided as a note for my repo: facts, decisions, open points. Mark anything you are not sure of." Paste it in (VS Code, or tell a Code session "save this as docs/notes/…").
- Facts from chat are `raw` until a Code session or you check them against the data or the source. Venue histories and API details are the usual traps.
- A note that changes the plan is not enough: a Code session must turn it into a `DECISIONS.md` entry and the matching plan/config edit.
- Site text drafts go to `docs/notes/drafts/` and are moved into `web/` by a build session.
- Going the other way: to ask chat about the project, the chat Project already has `CLAUDE.md`, `PLAN.md`, `DECISIONS.md`. For anything else paste the specific section, not the repo.

---

## 8. Mistakes to avoid

1. **Scope creep.** The parking lot exists so ideas do not become code. Features enter only through a roadmap edit at a gate.
2. **Unreviewed large diffs.** If a PR is too big to read, the session was too big. Split next time; for this one, get an independent review session and read the risky files yourself.
3. **Untested data transforms.** A parser or merge rule without a fixture test will silently rot. CI refuses nothing by itself: you refuse the PR.
4. **Secrets in a public repo.** Keys only in `.env`; `gitleaks` in pre-commit and CI; never paste a key into a chat or a prompt; if one leaks, revoke it first, then clean history.
5. **Trusting "done".** Ask for evidence (test output, row samples, screenshots). Look at real rows after every data session.
6. **Trusting facts from memory**, the model's or yours: venue years, API limits, licences. Check against the source; record the date.
7. **Polishing the pilot.** The pilot's job is to prove the whole chain on three venues. Rough but end-to-end beats beautiful and partial.
8. **Hand-fixing data.** A wrong tag is fixed in the taxonomy, a dictionary or the tagger, never in the output.
9. **Re-running harvests by habit.** The cache makes re-parsing free; hitting the APIs again is slow and impolite.
10. **Letting the taxonomy review slip.** Everything after P1-06 is built on it. Block the 2–4 hours in your calendar.
11. **Building on the server before it exists.** Phase 3 starts with containers on the Mac so nothing waits on IT.
12. **Changing the plan silently.** If a session deviates, it writes a decision. Future sessions only know what is written.
13. **Long sessions when tired.** Approving plans and diffs is the job; an inattentive "yes" is how bad merges happen. Stop at a checkpoint and continue another day.
