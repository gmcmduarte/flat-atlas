# P1-07b — Local decision model for the unsure works

**Tool:** Claude Code · **Model:** Sonnet · **Branch:** `s/P1-07b-decision-model` · **Depends on:** P1-07

You are working on The FLAT Atlas. You have no memory of earlier sessions. Everything you need is in the repo.

## Read first
1. `CLAUDE.md` (hard rules 2, 3 and 7 matter most here)
2. `docs/plan/PROGRESS.md` (top section and the latest hand-off note only)
3. `docs/plan/PLAN.md` §9 intro, §9.3 ("Composite text"), §9.5, §9.8
4. `docs/plan/DECISIONS.md` D-63, D-64, D-67
5. `config/tagger.yaml`, `docs/notes/tagger-experiments.md`

Then use plan mode: list the steps and the files you will create or change, and wait for my approval before coding.

## Goal
Cascade step 3: for the works the fusion model is unsure about, ask an open model running **on this machine** which topics fit, by reading option probabilities instead of generating text, and feed the calibrated answer back into the fusion model as one more signal.

## Cost
€0. Open weights, local inference, no network at inference time. **Do not add a client for any hosted model (Azure, OpenAI-compatible gateways, any other).** D-67 is a proposal that is not active; if you think a hosted model is needed, write that in the hand-off note and stop there. The only download is the model file (3–6 GB); check free disk first and tell me the size before downloading.

## Build
- **Choose the model and runtime.** Candidates: an open Qwen instruct model of 4–9B parameters in a quantised build, through llama.cpp (`llama-cpp-python`) or MLX. Requirements: weights openly downloadable under a licence that allows this use (read the licence, record it in `docs/notes/sources.md`), fits 16 GB RAM with room to spare, exposes next-token log-probabilities. Check the current model cards; do not rely on memory for names or sizes. Dependencies go in a new optional `llm` extra.
- `tagging/decide/scorer.py`: an interface `score(prompt, options) -> probabilities` with two implementations: the local model (one forward pass, probabilities of the option tokens renormalised over the options; handle options that are several tokens long by using single-token labels such as letters) and a deterministic `FakeScorer` for tests and CI. No sampling, no generated text.
- `tagging/decide/questions.py`: prompt builders, versioned (`prompt_version`):
  - *choice* over the level-0 topics (name + one-line description);
  - *yes/no* for one topic.
  Put the part shared between calls first so that the runtime can cache it. The paper text is the composite text of P1-05.
- `tagging/decide/run.py`: select the unsure works (band and disagreement rule from `config/tagger.yaml`); ask the choice question in 3 fixed option orders and average; ask yes/no for each child of the two most probable level-0 topics and for shortlisted candidates below them, capped per work; cache every answer in `local_decision` keyed by (work, question, option order, model SHA-256, prompt version); resumable; `--limit`; progress and works-per-minute in the log.
- Calibration: isotonic regression per question type on gold-train (never held-out). Write `dm_l0` and `dm_child` to `tag_signal`; retrain the fusion model of P1-07 with the two new features (null where the step did not run) by the same cross-validation.
- `flatatlas tag decide [--limit N] [--all]` (`--all` scores every work, for the measurement below) and `flatatlas tag --method fusion` picking up the new signals. `--explain` shows the questions asked and the probabilities.
- Provenance: model file name, SHA-256, quantisation, runtime version, prompt version.
- **Measure before the long run** (with `--limit 50`): seconds per work with 1 and with 3 option orders, tokens per work, peak memory, and the size of the order effect (how far the top probability moves between orders). Write them to `docs/notes/tagger-experiments.md` and replace the ⚠ estimates in PLAN §9.5 and §9.8 with the measured numbers.

## Test
- Unit tests with `FakeScorer`: prompt builders (stable text, shared prefix first); option shuffling and averaging (a scorer biased towards the first option is corrected); selection of unsure works; the cap on questions; cache hit means no model call; resume after an interruption; calibration monotonic; the held-out guard.
- The default test run and CI never load a real model.

## Done when
- `--limit 50` runs end to end on the Mac and the measurements are recorded.
- The projected time for the full pilot run is stated, and the run is practical (if it would take more than two nights, say so and propose a cut: fewer option orders, a smaller model, a narrower band).
- After the long job: every unsure pilot work has `dm_*` signals; cross-validated F1 on gold-train with and without the decision model is in `tagger-experiments.md`. **No held-out number is computed in this session** (P1-08 does that once, for all methods).
- No code path in the repo can send text to a hosted model.

## Long job (Guilherme launches it, not you)
Prove the command works with `--limit 50`. Then give me the exact full command, wrapped as `caffeinate -i uv run flatatlas tag decide … 2>&1 | tee data/logs/<date>-tag-decide.log`. Run it with `--all` if the projected time is under about 3 hours (it gives P1-08 the cleanest comparison), otherwise on the unsure works only. Stop and wait. When I say it finished, read the log tail and continue.

## Out of scope
- Propagation, held-out evaluation, the method comparison (P1-08). The distilled classifier (P4-05). Any hosted API, including a "just to compare" run.

## At the end
- Run `uv run pytest` and `uv run ruff check .` and show me the output.
- Go through "Done when" line by line: pass or fail, with evidence.
- Update `docs/plan/PROGRESS.md`: tick P1-07b, add a dated entry (built, not built, surprises) and a hand-off note for P1-08: the measured speed, the share of works scored, where the cached answers live.
- Record any decision you made in `docs/plan/DECISIONS.md` (the model and runtime chosen, with the licence).
- Commit, push the branch and open a PR to `main`. Do not merge.
