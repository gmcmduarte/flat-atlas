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
