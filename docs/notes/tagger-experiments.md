# Tagger experiments (P1-07)

Numbers from P1-07, cascade steps 1 and 2 (signals, shortlist, learned fusion). Everything here is
judged on **gold-train by cross-validation**; **no held-out number is computed in this session**
(the held-out evaluation and the method comparison are P1-08).

Read every precision, recall and F1 as **agreement with the labelled set**, which is Claude's
reading of the papers: the 500 random works approved by Guilherme without changes (D-91), the 182
top-up works reviewed by Claude (D-93, D-94). Numbers differ by a point or two between runs of a
different setting; with 341 works, differences under about 0.02 are noise.

Reproduce: `uv run flatatlas tag fit` (cross-validation, tuning, model), `tag artefacts` (shortlist
recall), `tag anchors`, `tag experiment emb-desc`, `tag experiment local-embedding`. Settings:
`config/tagger.yaml`, `tagger_version: tagger-1`.

## How the numbers are made

- **Works scored:** the 341 random-sample works with `split: train` ("random-train"), and all 523
  `train` works including the 182 top-up works ("all-train"). Top-up works are not a random sample,
  so they train the models but are never used for the calibrator, the selection tuning, base rates
  or the venue prior. The headline numbers are the random-train ones.
- **Cross-validation:** 5 folds, the fold of a work is a hash of its ID. For each fold the whole
  chain (stage A, stage B, isotonic calibration) is fitted on the other folds plus the silver
  pairs, and scores the fold. Inside each fit, stage B is trained on out-of-fold stage-A
  probabilities, and the calibrator on out-of-fold stage-B probabilities of random-sample gold
  pairs (nested; nothing sees the work it scores).
- **Selection** (threshold and maximum number of topics) is tuned on random-train by the mean of
  the level 0 and level 1 micro F1, separately for each method: fusion 0.45 and 3, noisy-or 0.55
  and 3 (the starting values were 0.35 and 6).
- **Predicted tags at a level** are the selected topics plus the derived ancestors at that level;
  **gold tags** are the labels at that level. Micro scores pool all (work, topic) cells; macro F1
  averages over topics with at least 5 gold positives in the scored works (the thinner topics are
  counted, not scored).
- **Unsure share:** share of works with at least one level 0 or level 1 pair whose calibrated
  probability is inside a band. The configured band is 0.3 to 0.5, around the tuned threshold.

## Cross-validated precision, recall and F1 (random-train, 341 works)

| Method | Level 0 P | R | F1 | Level 1 P | R | F1 | Macro F1 L0 (19 topics) | Macro F1 L1 (40 topics) | Unsure share |
|---|---|---|---|---|---|---|---|---|---|
| (a) noisy-or | 0.630 | 0.804 | 0.706 | 0.599 | 0.733 | 0.659 | 0.697 | 0.695 | 69 % |
| (c) logistic fusion | 0.668 | 0.805 | 0.730 | 0.757 | 0.653 | 0.701 | 0.737 | 0.688 | 62 % |
| (c) LightGBM fusion (kept) | 0.777 | 0.825 | **0.800** | 0.822 | 0.672 | **0.740** | 0.800 | 0.725 | **37 %** |

All 523 train works (including top-up): LightGBM F1 0.810 at level 0 and 0.765 at level 1;
logistic 0.751 and 0.730; noisy-or 0.727 and 0.680. Level-1 topics with 1 to 4 positives are left out of the macro score: 72 among the random-train
works, 19 among the all-train works.

**Choice between the two learned models:** LightGBM beats logistic regression by 0.05 in the mean
of the level 0 and level 1 F1, more than the margin of 0.01 in `fusion.complex_margin`, so the more
complex model is kept (the rule is "the simpler unless the other is clearly better").

**Unsure band for P1-07b:** share of random-train works with a level 0 or 1 pair in the band, for
the shipped fusion model:

| Band | 0.2 to 0.6 | 0.25 to 0.55 | **0.3 to 0.5** | 0.35 to 0.45 |
|---|---|---|---|---|
| Unsure share | 71 % | 64 % | **37 %** | 27 % |

On all 2,333 pilot works the share at 0.3 to 0.5 is 47.5 % (works outside the labelled set are
less typical of FLAT). The PLAN estimate of 30 to 40 % holds for the labelled works only at the
narrow bands; P1-07b should choose the band by how many works it can afford to send on.

## Shortlist recall (gold-train)

Shortlist: 10 candidate topics per work (lexical 4, seed embedding 4, description embedding 2,
OpenAlex 1, filled by noisy-or), plus ancestors; 14 pairs per work on average with ancestors.

| Works | Level 0 | Level 1 | All labels | Labels | Missed |
|---|---|---|---|---|---|
| all gold-train (523) | 95.1 % | 89.7 % | **92.4 %** | 1,679 | 128 |
| random gold-train (341) | 94.0 % | 89.1 % | 91.6 % | 1,043 | 88 |

**The target of 95 % is not reached; the misses by cause** (all gold-train):

| Cause | Level 0 | Level 1 |
|---|---|---|
| A phrase matched, but other topics filled the lexical quota | 13 | 33 |
| An embedding percentile of 0.8 or more lost to other topics | 9 | 26 |
| No signal above its floor (title and references carry nothing the dictionary or the embedding knows) | 18 | 29 |

The third row is a limit of the signals (for example "Synchronization of Communication" labelled
`codes`), not of the shortlist size. I tried growing the shortlist: 8 candidates 90.2 %, 10 91.7 %,
12 93.0 % (all labels, before the local-embedding change); adding the children of the two best
level-0 topics 92.0 to 93.3 %. None reaches 95 %, and the extra pairs would dilute the learned
model, so the shortlist stays at 10 and the misses are listed here. A missed label can never be
recovered; level 1 recall of the whole tagger is bounded by 89.7 %.

## Anchors

`flatatlas tag anchors`: the expected topic is among the 3 most probable topics (calibrated fusion
probability, all levels) for **134 of 147 in-corpus anchors (91 %)**: 102 of 113 (90 %) for anchors
that are not in `gold.yaml`, 32 of 34 (94 %) for anchors that are gold-train works (in-sample).
Anchors that are held-out works are skipped. The misses are mostly deep topics (level 2) that the
tagger puts under their parent or a sibling, for example `nfa-reduction` →
`nondeterministic-finite-automata`. The target was 80 %.

## Experiment 1: how to embed the topic description for `emb_desc`

Three variants, each replacing `emb_desc` and nothing else (local input `title_refs`, LightGBM
fusion). "AP" is the average precision of the one signal on level 0 and level 1 labels of the
random-train works (pooled over work-topic pairs; the percentile is not comparable across topics,
so the absolute values are low); F1 is the cross-validated fusion F1 as above.

| Variant | AP both | AP level 0 | AP level 1 | Fusion F1 level 0 | level 1 | Mean |
|---|---|---|---|---|---|---|
| `specter2`: proximity adapter on the topic text (kept) | 0.161 | 0.217 | 0.190 | 0.800 | 0.740 | 0.770 |
| `specter2_adhoc`: ad-hoc query adapter on the topic text | 0.190 | 0.256 | 0.219 | 0.783 | 0.740 | 0.762 |
| `minilm`: `all-MiniLM-L6-v2` for topics and for works | **0.322** | 0.381 | 0.407 | 0.791 | 0.740 | 0.765 |

**Result:** the general sentence model is twice as good *as a single signal*, but the fusion F1 is
the same within noise for all three (0.762 to 0.770). **The proximity adapter stays** (nothing to
download, no second model, works embedded once for all signals). A candidate to revisit: the
fusion already gets topic knowledge from `emb_seed` and the phrases, so `emb_desc` matters most
where those are thin, the 20 level-1 topics with fewer than 5 training works, and gold-train
cannot measure that. P1-08 can test `minilm` on the held-out set at the same time as the method
comparison; it only needs `description_model: minilm` in `config/tagger.yaml` (and a new
`tagger_version`).

Downloads for this experiment (approved by Guilherme): `allenai/specter2_adhoc_query` (adapter,
small) and `sentence-transformers/all-MiniLM-L6-v2` (about 90 MB, Apache-2.0).

## Experiment 2: local SPECTER2 vectors for works without a Semantic Scholar vector

453 of 2,333 works have no S2 vector. Three inputs to the local model, judged on the gold-train
works among them (64 random-train, 96 all-train; a small set, so read the differences with care):

| Input | AP `emb_seed` | AP `emb_desc` | Fusion F1 level 0 | level 1 | Mean (random-train) | Mean (all-train) |
|---|---|---|---|---|---|---|
| `stored` (P1-03: title, plus the abstract when there is one) | 0.070 | 0.119 | 0.692 | 0.671 | 0.682 | 0.730 |
| `title` alone | 0.069 | 0.116 | 0.674 | 0.648 | 0.661 | 0.711 |
| `title_refs`: title, then the cleaned titles of up to 10 references (kept) | **0.123** | **0.169** | **0.764** | **0.710** | **0.737** | **0.772** |

**Result:** adding the reference titles lifts the F1 of these works by about 0.055, and the two
embedding signals by about 70 %, in line with D-64 (references describe a paper better than a
short title). `embedding.local_input: title_refs` in `config/tagger.yaml`. The S2 vectors of the
other 1,880 works are not changed.

## Optional experiment 3: SciEmbed against SPECTER2

**Not run.** The weights are on Hugging Face (`J0nasW/sciembed-full` and sibling checkpoints, 149M
parameters, about 600 MB). The model cards state the MIT licence; I read the cards through a
search result and did not open the repositories' LICENSE files, so the licence is **declared, not
verified**. Guilherme approved the other two downloads and not this one. D-23 is unchanged. If it
is wanted later, a 600 MB download and the licence check come first.

## Other numbers

- **Training pairs:** 33,005 pairs for 2,333 works (23,330 candidates, the rest ancestors). Gold:
  4,271 random pairs (955 positive) and 2,347 top-up pairs (596 positive). Silver: 2,207 pairs from
  277 works, **37 positive and 2,170 negative**. Silver positives need `lex_title` of at least 0.85
  *and* a mapped OpenAlex topic, and only 4 % of (work, topic) cells have an OpenAlex mapping, so
  silver mostly adds negatives from distant top-level topics. `src_msc` does not exist yet
  (Phase 6).
- **Weights in the fit:** gold 3, silver 1. The calibrator is fitted on the 4,271 out-of-fold
  random-sample gold pairs.
- **Timing (M1, artefact cache emptied first):** `tag --method noisy_or` (corpus, artefacts, signals,
  shortlist, pair features, tagging) 15 s; `tag --method fusion`, which also cross-validates the
  three methods, tunes the selection and fits and saves the final model, 17 s more. Loading
  SPECTER2 to embed the 181 topic descriptions adds about 20 s the first time (the vectors are
  then cached). **Well under the budget of 10 minutes.**
- **Coverage:** with the fusion model 2,279 of 2,333 works have tags (97.7 %), 54 are listed as
  untagged (`data/reports/tag-untagged-fusion.txt`), 144 carry a low-confidence tag (best level-0
  topic, probability at least 0.15); noisy-or: 2,259 tagged, 74 untagged, 54 low-confidence.
- **Held-out works named in `topics.yaml`:** 46 of the `seed_works` are held-out works. The tagger
  drops them from its seed sets; the list is in `taxonomy/proposals/seed-works-heldout.md`.
- **Multi-centroid topics:** with a spread threshold of 0.05 (mean cosine distance of the seeds to
  their centroid; the median over topics is 0.04, because SPECTER2 vectors of one subfield sit
  close together) 13 topics get more than one centroid.

# Decision model (P1-07b): measurements before the long run

Cascade step 3 (PLAN §9.5). Model: `Qwen3-8B-Q4_K_M.gguf` (Apache-2.0, `docs/notes/sources.md`),
`llama-cpp-python` 0.3.37 with Metal, prompt version `dm-1`, Apple M1 with 16 GB. Measured with
`flatatlas tag decide --bench --limit 50` (answers kept in memory, so no cache helped): the first
50 unsure works by ID, 3 option orders, up to 8 yes/no questions per work
(`data/reports/dm-bench-50.json`, log `data/logs/2026-11-19-dm-bench-50.log`). **These numbers are
speed and stability only; nothing here says how good the answers are** (that is the cross-validated
comparison after the long run, and the held-out numbers are P1-08).

| What | Measured |
|---|---|
| Seconds per work, 3 option orders + up to 8 yes/no | **22.6** (1,130 s for 50 works) |
| Seconds per work, 1 option order + up to 8 yes/no | **14.7** (3.95 + 10.7; the yes/no step is the same) |
| Choice question, one order | 3.95 s; 280 tokens evaluated of 1,284 in the prompt (the option list is served from the cache) |
| Yes/no questions, 8 per work | 10.7 s; 722 tokens evaluated of 2,993 (the paper text is shared by a work's questions) |
| Tokens evaluated per work (3 orders + yes/no) | about 1,560 of 6,840 in the prompts (77 % served from the cache) |
| Throughput | about 80 evaluated tokens/s; `flash_attn` and `n_batch` 1024 did not help (76 and 74 tokens/s on a 6-prompt test) |
| Peak memory (process) | 5.8 GB (model 5.0 GB plus the key-value cache and Python) |
| Questions asked | 150 choice, 400 yes/no |

**Order effect** (the same question with the options in three fixed orders; 50 works, all unsure):
the most probable topic is the same in all three orders for **54 %** of works; the probability of
the averaged top topic moves by **0.44** on average between orders and by 1.0 at most. Answers are
often saturated (0.00 or 1.00 in one order, the opposite in another), which is why the three orders
are averaged and the result is calibrated before it is used. A single order is not enough for the
works this step exists for. Settings tried earlier on 5 works (a first version with 12 yes/no
questions and the full topic description) took 28.7 s per work; shortening the yes/no topic text to
its first sentence and capping the questions at 8 gives the 22.6 s above.

**Layout of the yes/no question:** paper first, topic last, so the paper is evaluated once per
work. With the topic first the paper (about 250 to 300 tokens) would be evaluated for every
question, about 5 times the tokens per question (computed from the token counts, not run).

**Projection.** Works the step runs on: the band 0.3 to 0.5 of the base fusion model (out of fold
for gold-train works) plus works where two signal families back different level-0 topics:

| Band | Band only | Band + disagreement | Share of random-train works | Time at 22.6 s/work |
|---|---|---|---|---|
| 0.35 to 0.45 | 382 | 611 (26 %) | 35 % | 3.8 h |
| **0.30 to 0.50 (chosen)** | 1,055 | **1,173 (50 %)** | 44 % | **7.4 h** |
| 0.25 to 0.55 | 1,240 | 1,335 (57 %) | 68 % | 8.4 h |
| all works | - | 2,333 | - | 14.6 h |

**Band chosen: 0.3 to 0.5 plus disagreement** (what `config/tagger.yaml` already had): the widest
band that fits one night (about 8 h) with margin; 0.25 to 0.55 would need 8.4 h. `--all` would
take 14.6 h, far over the 3 h limit, so the long run is on the unsure works only. The choice used
no held-out work (the base probabilities are out of fold for gold-train works and come from the
final model for the rest; no label of a held-out work enters).
**Field scale:** at 22.6 s per work, 150,000 unsure works of a 300,000-work field would take about
940 hours (39 days); with 1 order 610 hours. That is not practical on this machine; PLAN §9.8 is
corrected (it assumed 30 to 70 hours). The way out is step 4 (the distilled classifier trained on
the pilot's answers), a smaller model, or fewer questions; Qwen3-4B (2.5 GB) would be about twice
as fast, untested.

# Decision model (P1-07b): the full run and the cross-validated comparison

**The run** (`data/logs/2026-11-19-tag-decide.log`, 16:41 to 22:27, launched by Guilherme):
`flatatlas tag decide` over the **1,173 unsure works** (band 0.3 to 0.5 of the base model, out of fold
for gold-train works, plus the 281 works where signal families disagree; 50 % of the pilot).
3,510 choice and 9,360 yes/no questions asked (9 and 24 more were served from the cache of the
3-work test), no errors, **5.8 h
= 17.7 s per work** (choice 2.7, 2.8 and 3.1 s per order, yes/no 9.1 s for 7.98 questions on average;
the 50-work test above measured 22.6 s because of start-up and a cold cache). Peak memory 5.65 GB.
**Order effect over all 1,173 works:** the top topic is the same in all three orders for 58.5 %,
the top probability moves by 0.40 on average. Every one of the 1,173 works has `dm_l0` in
`tag_signal` (16,698 pairs) and 1,123 have `dm_child` too (3,648 pairs; the other 50 had no
level-1 candidate to ask about). Answers are cached in `warehouse/local/local_decision.parquet`
(12,903 rows).

**Cross-validated comparison on gold-train** (5 folds by work, the same folds as above; LightGBM,
same hyper-parameters; the decision model's raw answers are calibrated inside each fold by isotonic
maps fitted on that fold's random-sample training pairs: 835 level-0 pairs and 475 level-1 pairs in
the final fit). Selection retuned for each: base threshold 0.45 and 3 topics, with the decision model
0.4 and 3. **No held-out number.** Scores are agreement with the labelled set (Claude's reading).

| Works | Model | Level 0 P | R | F1 | Level 1 P | R | F1 | Mean F1 |
|---|---|---|---|---|---|---|---|---|
| random-train (341) | base | 0.777 | 0.825 | **0.800** | 0.822 | 0.672 | 0.740 | 0.7697 |
| random-train (341) | with decision model | 0.767 | 0.823 | 0.794 | 0.796 | 0.700 | **0.745** | 0.7694 |
| all-train (523) | base | 0.791 | 0.830 | 0.810 | 0.843 | 0.701 | 0.765 | 0.7875 |
| all-train (523) | with decision model | 0.781 | 0.829 | 0.804 | 0.820 | 0.726 | 0.770 | 0.7871 |

Macro F1 (random-train; 19 level-0 and 40 level-1 topics): level 0 0.800 to 0.795, level 1 0.725 to
0.737. Unsure share at the band 0.3 to 0.5: 37.0 % to 40.2 %.

**On the works the step ran on only** (the unsure works; their out-of-fold probabilities):

| Works | Model | Level 0 F1 | Level 1 P | R | F1 |
|---|---|---|---|---|---|
| unsure, random-train (150) | base | 0.786 | 0.796 | 0.656 | 0.719 |
| unsure, random-train (150) | with decision model | 0.780 | 0.757 | 0.713 | 0.734 |
| unsure, all-train (234) | base | 0.789 | 0.819 | 0.672 | 0.738 |
| unsure, all-train (234) | with decision model | 0.785 | 0.787 | 0.721 | 0.753 |
| not unsure, random-train (191, no `dm_*`) | base | 0.813 | 0.846 | 0.686 | 0.757 |
| not unsure, random-train (191, no `dm_*`) | with decision model | 0.806 | 0.835 | 0.689 | 0.755 |

**Reading.** With 341 works, differences under about 0.02 are noise (above). **The decision model
changes nothing measurable.** The mean of the level 0 and level 1 F1 is 0.7697 against 0.7694. On the
unsure works it moves level 1 recall up (0.656 to 0.713) and precision down (0.796 to 0.757), a
level 1 F1 gain of 0.015 (0.015 on the 234 all-train works too), against a drift of 0.002 to 0.007
on the *unchanged* works (no `dm_*` at all; only the retuned selection differs). That gain is about
twice the drift and below the 0.02 that 341 works can resolve, and level 0 loses 0.004 to 0.006. Taken alone,
the choice question is worse than the fusion model: the most probable topic is one of the work's
gold level-0 labels for **80.7 %** of the 150 unsure random-train works (82.1 % of 234 all-train),
against **91.3 %** for the base model's top level-0 topic on the same 150 works. The model is
overconfident (many 0.00 or 1.00 per order) and changes its mind with the option order.
Held-out numbers (P1-08) decide whether step 3 stays; on this evidence it would not earn its 5.8 h
(and at field scale 740 h), unless a smaller model, a better prompt or a different use of the
answer (for example only as a tie-breaker) is tried. Side effect to know: with the decision model
the retuned selection leaves 73 works untagged (54 without) and 117 low-confidence (144 without).

# P1-08: settings frozen before the held-out set was opened

Written **before** `flatatlas evaluate --heldout` was run; nothing below uses a held-out label.
Run `p1-08-tagger-3-084b04920e` (`flatatlas evaluate freeze`, `data/reports/frozen-<run>.json`,
which also holds the model and probability-file hashes and the work lists every fit used).
`tagger_version` is `tagger-3` (see "What changed" below). Numbers are cross-validated on
random-sample gold-train (341 works) or label-free checks on all 2,333 works. Scores are agreement
with the labelled set (Claude's reading, D-91, D-93).

## Method of the comparison

Eight variants: (a) noisy-or, (b) top-down, (c) learned fusion, (c) with the decision model, each
without and with propagation (pass 2). Every variant is fitted on gold-train (plus silver for the
fusion models) through `Guard`; the held-out works are scored as unlabelled works. The held-out
numbers come from probability files that were written here and hashed, so `--heldout` cannot
refit or retune anything: it refuses if `config/tagger.yaml` (apart from three adoption switches),
`gold.yaml`, `topics.yaml` or a probability file changed, or if a held-out work is in any recorded
training, calibration, seed or top-down set. It writes a lock file; a second opening needs
`--again` and its numbers are labelled optimistic.

**The adoption rule, as I read it before opening (PLAN §9.6).** The ladder is (a) → (c) → (c) with
the decision model; propagation is compared with the same method without it; (b) is a baseline
compared with (a) and (c). A more complex option is adopted only if the 90 % bootstrap interval
(2,000 resamples of the held-out works, the same resamples for every method) of the paired
difference in *mean of the level 0 and level 1 micro F1* excludes zero **and is positive**, and no
hard check gets worse. **"Gets worse" means: the simpler method meets the hard threshold and the
more complex one does not.** The reason for this reading: noisy-or is deterministic, so its
stability is exactly 1.000; if any fall counted as worse, no learned model could ever be adopted
over it, which cannot be what the rule is for. Drops that stay above their threshold are shown in
the report beside the verdict (for example anchors 0.946 for fusion against 0.986 for noisy-or).

## Frozen settings and the label-free checks

| Variant | Selection (threshold, max topics) | CV level 0 F1 | CV level 1 F1 | Anchors | Coverage | Stability | Venue sanity | Citation consistency |
|---|---|---|---|---|---|---|---|---|
| (c) fusion | 0.45, 3 | 0.794 | 0.742 | 139/147 = 0.946 | 0.911 | 0.960 | 10/10 | 0.853 |
| (c) + decision model | 0.4, 3 | 0.792 | 0.743 | 135/147 = 0.918 | 0.926 | 0.962 | 10/10 | 0.859 |
| (c) + decision model + propagation | 0.5, 3 | 0.807 | 0.753 | 137/147 = 0.932 | 0.916 | 0.964 | 10/10 | 0.882 |
| (c) + propagation | 0.5, 3 | 0.806 | 0.746 | 134/147 = 0.912 | 0.908 | 0.969 | 10/10 | 0.896 |
| (a) noisy-or | 0.55, 3 | 0.706 | 0.659 | 145/147 = 0.986 | 0.945 | 1.000 | 10/10 | 0.887 |
| (a) + propagation | 0.55, 3 | 0.717 | 0.671 | 144/147 = 0.980 | 0.955 | 1.000 | 10/10 | 0.930 |
| (b) top-down | 0.2, 3 | 0.613 | 0.420 | 65/147 = 0.442 | 0.954 | 1.000 | 9/10 | 0.809 |
| (b) + propagation | 0.2, 4 | 0.647 | 0.444 | 64/147 = 0.435 | 0.950 | 0.952 | 9/10 | 0.877 |

Hard thresholds: anchors ≥ 0.90, coverage ≥ 0.85 (works with at least one non-derived tag above the
threshold; the low-confidence fallback tag is not counted), stability ≥ 0.95, all venue
expectations. **Every fusion variant passes all four; (b) fails anchors and venue sanity** (it
scores levels 0 and 1 only, and its level-1 F1 is 0.42), so it cannot be adopted. The selection of
each variant is tuned on out-of-fold probabilities of random-sample gold-train works only.

**Propagation.** The in-corpus citation graph is thin: 2,211 edges for 2,333 works, and
`is_influential` is null on every edge, so the influential boost has no effect here. `prop_cite`
(references weight 1, citers 0.25) and `prop_author` (±5 years) were tuned on gold-train
cross-validation only: citer weight 0.25 against 0.5 (fusion mean F1 0.7705 against 0.7679, flat);
noisy-or weights over `prop_cite` {0.2 to 1.0} and `prop_author` {0 to 0.3}: 0.6 and 0.1 (mean
F1 0.683 to 0.694). Pass-1 vectors come from the variant's own method (from the base fusion for
both fusion variants), out of fold for gold-train works. Cross-validated, propagation adds about
0.01 to the noisy-or F1 and 0.01 at level 0 to the fusion; the held-out set decides.

**Decision-model coverage.** All 1,173 unsure works have answers. Under pass 2 the unsure set is
the one chosen from pass-1 probabilities (the band is not moved), so no new works become unsure.

**Method agreement** (label-free, level 0, top-1): lexical against embedding 0.512 (2,002 works),
lexical against source 0.548 (292), embedding against source 0.649 (251). Twelve level-0 topics
have a mean per-topic Jaccard under 0.2 (list in the report).

**Hold-out leak test** (200 unlabelled works whose `lex_title` is set to 0, shortlist and features
rebuilt): the fusion keeps 57 % of the tags and 54 % of the primary tags, noisy-or 68 % and 64 %.
The learned model leans on the title match more than noisy-or does. (A first version of this test
set the title signal to NaN and got 21 %: in training, NaN `lex_title` marks silver pairs, 98 %
negative, so the model read "missing" as "negative". Real works never have NaN there, so the test
now uses 0.)

## What changed on the way (all before the opening, none uses a held-out label)

1. **Stability of the learned fusion.** With one model, 7.5 % of the primary tags changed under
   another seed (stability 0.925, below the 0.95 threshold; noisy-or 1.000). Variance experiments
   (artefacts fixed, final fits only): without row and column subsampling 0.939; with the fold
   assignment fixed as well 1.000, so the variance comes from the folds that feed stage B and the
   calibrator and from LightGBM's sampling, which flip near-tied topics. Averaging the calibrated
   probabilities of several models fitted under different seeds: 3 models 0.937, **5 models 0.960**,
   9 models 0.974. Guilherme chose to bag the fusion model (asked in this session): `fusion.bag: 5`,
   member *k* fitted with seed + 101 *k*, member 0 is the single model of `tagger-2`.
   Cross-validated F1 of the bagged fusion is within noise of the single model (level 0 0.794 against
   0.800, level 1 0.742 against 0.740). `tagger_version` is now `tagger-3`.
2. The top-down baseline's logistic regression uses C = 0.1 (best of 0.001 to 10 by cross-validated
   mean F1: 0.358, 0.511, 0.516, 0.511, 0.509); the selection threshold grid was checked down to
   0.05 and its optimum (0.2) is not at the edge.


# P1-08: the held-out comparison (opened once)

**This is the only opening of the held-out set** (`flatatlas evaluate --heldout`, run
`p1-08-tagger-3-084b04920e`, `data/reports/heldout-<run>.json`, lock file
`data/reports/heldout-opened.json`). The settings are those frozen in the section above; nothing was
changed after seeing these numbers except the three adoption switches the rule decides
(`method`, `decision_model.enabled`, `propagation.enabled`). **159 held-out works, 242
gold labels at level 0 and 241 at level 1.** Scores are **agreement with the labelled set**, which is
Claude's reading of the papers (500 random works approved by Guilherme without changes, 182
top-up works reviewed by Claude); they are not agreement with the truth. Intervals are 90 %
bootstrap intervals over the held-out works (2,000 resamples, the same for every method, so the
paired differences are paired).

## The comparison table

| Method | Level 0 P | R | F1 | Level 1 P | R | F1 | Macro F1 L0 | Macro F1 L1 | Mean of the F1s | Paired Δ mean F1 against the simpler neighbour (90 %) | Hard checks that fail |
|---|---|---|---|---|---|---|---|---|---|---|---|
| (a) noisy-or | 0.627 (0.584–0.671) | 0.818 (0.779–0.858) | 0.710 (0.674–0.746) | 0.546 (0.505–0.590) | 0.710 (0.663–0.755) | 0.617 (0.578–0.656) | 0.697 (0.636–0.732) | 0.696 (0.595–0.755) | 0.664 (0.631–0.695) | – | none |
| (a) + propagation | 0.624 (0.583–0.666) | 0.843 (0.808–0.879) | 0.717 (0.684–0.750) | 0.523 (0.486–0.563) | 0.714 (0.667–0.760) | 0.604 (0.567–0.640) | 0.699 (0.640–0.732) | 0.671 (0.578–0.726) | 0.660 (0.633–0.689) | -0.003 (-0.017 to +0.011) | none |
| (b) top-down | 0.550 (0.510–0.590) | 0.632 (0.579–0.685) | 0.588 (0.548–0.628) | 0.662 (0.597–0.729) | 0.390 (0.336–0.444) | 0.491 (0.435–0.544) | 0.557 (0.495–0.592) | 0.551 (0.432–0.619) | 0.540 (0.497–0.580) | – | anchors, venue_sanity |
| (b) + propagation | 0.586 (0.547–0.626) | 0.645 (0.590–0.699) | 0.614 (0.572–0.653) | 0.658 (0.594–0.724) | 0.398 (0.346–0.452) | 0.496 (0.444–0.550) | 0.580 (0.515–0.618) | 0.551 (0.443–0.612) | 0.555 (0.516–0.594) | +0.015 (-0.006 to +0.038) | anchors, venue_sanity |
| (c) fusion (bagged) | 0.739 (0.692–0.785) | 0.785 (0.740–0.828) | 0.762 (0.724–0.798) | 0.805 (0.757–0.852) | 0.618 (0.568–0.668) | 0.700 (0.657–0.739) | 0.755 (0.698–0.789) | 0.696 (0.601–0.745) | 0.731 (0.696–0.762) | +0.067 (+0.038 to +0.096) **adopt** | none |
| (c) fusion + propagation | 0.776 (0.730–0.823) | 0.785 (0.744–0.826) | 0.780 (0.746–0.813) | 0.816 (0.768–0.861) | 0.627 (0.576–0.678) | 0.709 (0.667–0.748) | 0.765 (0.708–0.797) | 0.707 (0.605–0.761) | 0.745 (0.713–0.774) | +0.014 (-0.002 to +0.031) | none |
| (c) fusion + decision model | 0.756 (0.716–0.800) | 0.793 (0.751–0.838) | 0.774 (0.739–0.811) | 0.800 (0.754–0.845) | 0.647 (0.598–0.696) | 0.716 (0.676–0.753) | 0.768 (0.709–0.803) | 0.700 (0.609–0.750) | 0.745 (0.713–0.777) | +0.014 (-0.002 to +0.032) | none |
| (c) fusion + decision model + propagation | 0.769 (0.730–0.812) | 0.785 (0.742–0.828) | 0.777 (0.744–0.810) | 0.812 (0.770–0.856) | 0.643 (0.593–0.691) | 0.718 (0.678–0.756) | 0.759 (0.698–0.794) | 0.717 (0.622–0.772) | 0.747 (0.716–0.777) | +0.002 (-0.011 to +0.015) | none |

Reading, by the rule of PLAN §9.6 (interval of the paired difference in mean F1 excludes zero, is
positive, and no hard check fails that the simpler method passes):

- **(c) fusion over (a) noisy-or: adopted.** Mean F1 +0.067, interval
  +0.038 to +0.096; level 0 +0.052, level 1 +0.082. All hard
  checks pass for both. Fusion gives up some of what noisy-or has on the label-free checks (anchors
  0.946 against 0.986, coverage 0.911 against 0.945, stability 0.960 against 1.000), all above the
  thresholds.
- **The decision model (step 3) does not earn its place: not adopted.** Mean F1 +0.014,
  interval -0.002 to +0.032, which includes zero (level 0 +0.013, level 1
  +0.016); it also costs four anchors (0.946 to 0.918). **`decision_model.enabled` is now `false`.** The
  point estimate is positive and the interval only just reaches zero, so this is "not shown", not
  "shown not to help". Where it helps most is the thinnest text: works with no abstract (34 works)
  0.711 to 0.768, with no references (26 works) 0.663 to 0.723, but these groups are too small to
  say anything (see "by paper type").
- **Propagation does not earn its place: not adopted, for any method.** Noisy-or -0.003
  (-0.017 to +0.011), fusion +0.014 (-0.002 to +0.031),
  fusion with the decision model +0.002 (-0.011 to +0.015).
  The citation graph has 2,211 edges for 2,333 works and no influential flag, so there is little to
  propagate. `propagation.enabled` stays `false`.
- **(b) top-down is far behind** and is a baseline only: against (c) fusion -0.191 (-0.234 to -0.149),
  against (a) -0.124 (-0.170 to -0.078). It also fails anchors (0.442) and venue sanity (9 of 10),
  because it scores levels 0 and 1 only.

**Shipped method (D-100): (c) learned fusion, bagged over 5 seeds, without the decision model and
without propagation** (`method: fusion`, `decision_model.enabled: false`, `propagation.enabled:
false`, `tagger_version: tagger-3`). Its held-out numbers are the pilot's precision and recall:

| Level | Precision | Recall | F1 |
|---|---|---|---|
| 0 | 0.739 (0.692–0.785) | 0.785 (0.740–0.828) | 0.762 (0.724–0.798) |
| 1 | 0.805 (0.757–0.852) | 0.618 (0.568–0.668) | 0.700 (0.657–0.739) |

**Proposed floor for gate G1** (the lower end of the 90 % interval, rounded down to the
nearest 0.05): level 0 F1 ≥ 0.70, level 1 F1 ≥ 0.65; precision ≥ 0.65 at level 0 and ≥ 0.75 at
level 1; recall ≥ 0.70 at level 0 and ≥ 0.55 at level 1. Level 1 recall is the weak number (0.618):
the shortlist's recall bound at level 1 is 89.7 % (P1-07), and the model keeps at most 3 topics.

## Hard checks (label-free; the table of the frozen section, with the variants side by side)

| Method | Anchors | Coverage | Stability | Venue sanity |
|---|---|---|---|---|
| (a) noisy-or | 0.986 | 0.945 | 1.000 | 10/10 |
| (a) + propagation | 0.980 | 0.955 | 1.000 | 10/10 |
| (b) top-down | 0.442 | 0.954 | 1.000 | 9/10 |
| (b) + propagation | 0.435 | 0.950 | 0.952 | 9/10 |
| (c) fusion (bagged) | 0.946 | 0.911 | 0.960 | 10/10 |
| (c) fusion + propagation | 0.912 | 0.908 | 0.969 | 10/10 |
| (c) fusion + decision model | 0.918 | 0.926 | 0.962 | 10/10 |
| (c) fusion + decision model + propagation | 0.932 | 0.916 | 0.964 | 10/10 |

## Calibration (held-out, levels 0 and 1)

Fusion is close to calibrated: stated confidence against observed precision in bins of 0.1: 0.03 to
0.04, 0.15 to 0.19, 0.25 to 0.26, 0.34 to 0.37, 0.45 to 0.62, 0.55 to 0.58, 0.65 to 0.68, 0.75 to
0.80, **0.87 to 0.67** (48 pairs), 0.95 to 0.95. Noisy-or is not calibrated (stated 0.55 observed
0.14; 0.75 observed 0.48), which is expected for an uncalibrated score. The full curves are in the
report.

## By paper type (mean of level 0 and level 1 F1, held-out)

| Abstract | Works | (a) noisy-or | (c) fusion | (c) + decision model |
|---|---|---|---|---|
| abstract | 125 | 0.680 | 0.736 | 0.741 |
| no abstract | 34 | 0.604 | 0.711 | 0.768 |

| References | Works | (a) noisy-or | (c) fusion | (c) + decision model |
|---|---|---|---|---|
| 0 references | 26 | 0.639 | 0.663 | 0.723 |
| 1-9 references | 28 | 0.655 | 0.784 | 0.785 |
| 10+ references | 105 | 0.672 | 0.732 | 0.740 |

| Decade | Works | (a) noisy-or | (c) fusion | (c) + decision model |
|---|---|---|---|---|
| 1990s | 20 | 0.627 | 0.619 | 0.625 |
| 2000s | 64 | 0.697 | 0.746 | 0.767 |
| 2010s | 46 | 0.647 | 0.701 | 0.718 |
| 2020s | 29 | 0.642 | 0.816 | 0.816 |

Fusion is better than noisy-or in every group but the 1990s (20 works, 0.619 against 0.627). The
weakest groups for fusion are works with no references (0.663), the 1990s (0.619) and works without
an abstract (0.711): where the text is thinnest.

## Settings changed after seeing held-out numbers

None. The only edits after the opening are the adoption switches the rule decides:
`decision_model.enabled: true` to `false`; `method` and `propagation.enabled` were already `fusion`
and `false`. `tag fit` and `tag` were re-run with those switches and the shipped model reproduces the
frozen `fusion` variant's probabilities (largest difference 3e-8 over 33,005 pairs; the same model
and selection, 0.45 and 3 topics).


## Propagation: before and after (held-out F1, anchors, coverage)

| Method | Mean F1 before | after | Paired Δ (90 %) | Anchors before | after | Coverage before | after |
|---|---|---|---|---|---|---|---|
| (a) noisy-or | 0.664 | 0.660 | -0.003 (-0.017 to +0.011) | 145/147 | 144/147 | 0.945 | 0.955 |
| (c) fusion | 0.731 | 0.745 | +0.014 (-0.002 to +0.031) | 139/147 | 134/147 | 0.911 | 0.908 |
| (c) fusion + decision model | 0.745 | 0.747 | +0.002 (-0.011 to +0.015) | 135/147 | 137/147 | 0.926 | 0.916 |
| (b) top-down | 0.540 | 0.555 | +0.015 (-0.006 to +0.038) | 65/147 | 64/147 | 0.954 | 0.950 |

Propagation keeps the held-out F1 (the intervals all include zero) and coverage, but **the fusion
loses five anchors (139 to 134 of 147)** and the fusion with the decision model gains two; for
noisy-or one anchor is lost. The citation graph is thin (2,211 edges, no influential flags), so
there is little for the second pass to add; the "improves or keeps anchor accuracy" line of the
session's done-when list is therefore **not met for the fusion** (see PROGRESS).
