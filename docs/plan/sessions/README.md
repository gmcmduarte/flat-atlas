# Session prompts

One file per build session. Each is self-contained: open a **new** Claude Code session in the repo, set the model named on the file's second line, and paste the whole file.

- Order and acceptance criteria: `../ROADMAP.md`.
- How a session runs (checkpoints, review, merge): `../WORKFLOW.md` §3.
- `P0-00` and `P3-00` are checklists for Guilherme, not prompts.
- `GATE.md` is the phase review prompt (Opus, fresh session). Replace `<N>` with the phase number.

If a session turns out too big: stop at a clean point, let Claude write the hand-off note, and paste the same file into a new session with the first line "Continue this session from the hand-off note in PROGRESS.md".

If reality has moved away from a prompt (a file was renamed, a decision changed): fix the prompt file in the same PR. The prompts are part of the plan and must stay true.

| Phase | Files |
|---|---|
| 0 Foundations | `P0-00` (manual), `P0-01` … `P0-04` |
| 1 Pilot | `P1-01` … `P1-12` (with `P1-06b` after `P1-06` and `P1-07b` after `P1-07`), then gate G1 |
| 2 Widen | `P2-01` … `P2-04`, then gate G2 |
| 3 Server | `P3-00` (manual), `P3-01` … `P3-05`, then gate G3 |
| 4 Mass import | `P4-01` … `P4-05`, then gate G4 |
| 5 Features | `P5-01` … `P5-06`, then gate G5 |
| 6 History | `P6-01` … `P6-03`, then gate G6 |
