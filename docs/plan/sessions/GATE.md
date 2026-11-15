# GATE — Phase review (G<N>)

**Tool:** Claude Code, a **fresh** session · **Model:** **Opus** · **Branch:** `s/G<N>-review`

Replace `<N>` with the phase number before pasting.

You are the independent reviewer of Phase <N> of The FLAT Atlas. You did not build it. Your job is to find what is wrong or weak before the project builds on it. Be specific and evidence-based. Do not fix code in this session, except trivial documentation errors.

## Read first
1. `CLAUDE.md`
2. `docs/plan/ROADMAP.md`: the Phase <N> table and the gate paragraph under it
3. `docs/plan/PROGRESS.md`: all entries of Phase <N>
4. `docs/plan/WORKFLOW.md` §5
5. `docs/plan/RISKS.md` and `docs/plan/DECISIONS.md` (entries added during the phase)
6. The PLAN sections cited by the phase's session files, as needed

Use subagents for wide reading (code areas, long reports) so your own context stays for judgment.

## Do, in this order
1. **Acceptance criteria.** For every session of the phase, re-verify each "Done when" line by running the check yourself (tests, commands, queries). Table: criterion, evidence, pass/fail.
2. **Data quality** (phases with data changes). Run `uv run flatatlas evaluate --data` and the data-quality tests. Then query the warehouse yourself: counts per venue-year against the source's own counts; duplicate DOIs; works without year or venue; orphan authorships; share matched per source; merge-confidence histogram. Read 30 random merges and 30 random author mappings and judge each with a reason.
3. **Tagging** (from Phase 1). Run `uv run flatatlas evaluate`. Check every threshold of PLAN §9.6. Open the spot-check report and read 10 topics chosen across levels and sizes: list concrete wrong tags and name the likely cause for each (dictionary phrase, centroid, taxonomy structure, propagation, missing abstract). Check 5 anchors by hand with `flatatlas tag --explain`.
4. **Scope** (from Phase 2). Read 30 borderline, 20 random in, 20 random out. Is anything from verification or general combinatorics leaking in? Is real FLAT work left out?
5. **UI** (from Phase 1). With the browser, on the deployed site and at a mobile width: search three topics; topic → child → related topic → (bridge, when it exists); a paper; an author; a venue (compare view, when it exists); expand map bubbles three levels; toggle edge types; an empty search; a bad URL. Every page: sources shown, suggest link works, no console errors. Screenshots of problems.
6. **Server and security** (from Phase 3). Open ports, HTTPS and headers, admin authentication, rate limits, backup and restore evidence, secrets (`gitleaks` on full history; no keys in images or logs), dependency audit (`uv pip audit` or equivalent, `npm audit`).
7. **Code health.** CI status; a test exists for every data transform added in the phase (list any without); dead code and duplicated logic worth removing; README and runbooks match reality.
8. **Phase-specific question.** Answer the question in the gate paragraph of the roadmap for this phase.
9. **Plan check.** Are the next phase's sessions still right? Which risks changed? Is the server sizing still right? Propose concrete edits.

## Write
`docs/plan/reviews/G<N>-review.md`:
- **Verdict:** pass / pass with fixes / fail, in the first line.
- **Must fix before moving on:** numbered, each small enough for one short Sonnet session, with a ready-to-paste prompt for each.
- **Should fix later:** added to the parking lot.
- **Evidence tables** from steps 1–7.
- **Proposed plan edits:** exact changes to ROADMAP, session files, RISKS, PLAN.
- **What Guilherme should look at himself** (30–60 minutes): the specific report sections and pages where his FLAT expertise decides.

## At the end
- Apply the plan edits Guilherme approves (ROADMAP, session files, RISKS, DECISIONS).
- Update `docs/plan/PROGRESS.md`: gate result, date, the fix sessions to run, next session. Move old log entries of the phase to `docs/plan/archive/`.
- Commit, push, open a PR. Do not merge.
