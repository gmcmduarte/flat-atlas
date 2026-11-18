# Labelled set v1: review guide (P1-06b)

For Guilherme. This guide covers the review of the draft labels: 500 works, about 2 hours at 15 s per work. The result becomes `taxonomy/gold.yaml`: the only real measure of the tagger's precision and recall (PLAN §9.6, D-61).

**No blind subset.** On 2026-11-18 you chose to review drafted labels for all 500 works instead of labelling 50 works blind first (D-91). So there is no measure of how much the draft steers the review. Keep that in mind when you accept a label: a draft label you do not actively check counts as yours.

## The order of work

1. **Review the draft.** Pull, then go through `taxonomy/proposals/gold-draft.yaml` from the top. The works are in a fixed random order.
2. **Hand it back.** I run `flatatlas gold finalise`. It writes `taxonomy/gold.yaml`, sets `split` by the hash rule and `reviewed: true`, and never changes a label you set. It refuses to run, listing every problem, if a label is unknown or deeper than level 1, if a work has no level-0 label, or if a level-1 label is missing all of its parents. Then `flatatlas gold report` measures how many of my labels you changed, against the commit that holds my unreviewed draft.

## What a label means

- A label says the paper is **about** the topic: the topic is a contribution or the main object of study, not just a tool it uses or a field it mentions. A state-complexity paper that uses DFAs does not get `deterministic-finite-automata`. A paper that studies a new class of DFAs does.
- Label **every** level-0 and level-1 topic that applies, usually 1 to 3 at each level. In the draft the mean is 1.5 at each level.
- **A level-1 label needs its level-0 parent.** List both. A level-0 label on its own is fine when no level-1 topic fits. I did this for 21 works; their notes say why.
- `decision-problems` (level 1) has three parents: `regular-languages`, `grammars-and-context-free-languages` and `machine-models`. A paper deciding a property of a model gets `decision-problems` **and** the model's topic, and one of those three roots must be labelled too. Decision problems on tree grammars, ω-languages, regulated rewriting or language operations therefore cannot take it (see `taxonomy/proposals/gold-taxonomy-issues.md`).
- Quantum models go under their own root `quantum-computing-models`, never under `weighted-and-probabilistic-automata`, unless the paper also studies the probabilistic model in its own right.

## Surveys, bridge papers and odd cases

- **Surveys and invited talks** take the topics they survey, at both levels, even when that is four roots. Example: `W4MX4SGNDSY`, "Unambiguous Finite Automata".
- **Bridge papers** that connect two areas take both, if each side is a real contribution. If one side is only the motivation, it does not count: an XML motivation does not earn `documents-and-databases`.
- **Out-of-scope works.** A few sampled works are hardly FLAT: two obituaries, a puzzle-complexity paper, a cryptosystem, hazard algebra for circuits, software metrics, and a maximum-sum-segment algorithm. Every work needs a level-0 label, so the draft gives each the nearest root and says so in its note. Please keep them in the set, with the label you find least wrong. The sample is random, and dropping works by hand would bias it; P2-02's scope rule decides what the site shows. If you would rather remove them, delete the entries and say so in your reply; the report will record it.
- **Sources that lie.** In 10 works the Semantic Scholar TLDR belongs to another paper (unrelated patents, a scheduling paper), mostly DLT 1993 to 1999, and an eleventh (`WO7RGS2E3MQ`) is doubtful. I labelled those from title and references, and their notes say so. This is a data problem for P1-07 as well (parking lot).
- **Title-only works.** 87 works carry a note that starts with "Title only" or "Title and references only". Some of their labels are guesses.

## Conventions I followed (so the labels are consistent)

- State complexity of operations: `descriptional-complexity` and `state-complexity-of-operations`. I added `regular-languages` and a level-1 regular topic only when the paper is also about a class or kind of automaton: subregular classes, permutation DFAs, unary languages, two-way automata.
- "Most complex languages" and the size of syntactic semigroups: also `syntactic-complexity`.
- Average-case and enumeration results: also `implementation-and-applications` and `random-generation-and-enumeration`.
- Building minimal acyclic DFAs for dictionaries: `regular-languages`, `minimisation-of-automata` and `implementation-and-applications`, plus `finite-state-nlp` when the paper is about lexicons.
- Restarting and forgetting automata: `machine-models` and `restarting-automata`. With Marcus contextual grammars, also `rewriting-systems` and `contextual-grammars`.
- Small universal devices: `machine-models` and `turing-machines`, plus the device's own topic.
- Weighted tree transducers: `transducers`, `tree-languages` and `tree-transducers`, with `weighted-and-probabilistic-automata` at level 0 only. Weighted tree automata get `weighted-tree-automata`.
- Hyper-minimisation, cover automata and NFA reduction: `minimisation-of-automata`.
- Synchronisation in Caucal's sense (pushdown automata synchronised by a transducer) is **not** `synchronizing-automata`.

The confusable pairs listed in `docs/notes/taxonomy-v1-review-guide.md` ("Topics hard to tell apart") are the places where your labels and mine are most likely to differ.

## How to edit the YAML (VS Code)

Each work looks like this:

```yaml
- work: WABVXJ254NQ
  # CIAA 2016 · https://doi.org/10.1007/978-3-319-40946-7_15 · https://dblp.org/rec/conf/wia/KisielewiczKS16
  title: "Experiments with Synchronizing Automata"
  labels: [regular-languages, synchronizing-automata]
  split: train
  sampling: random
  blind: false
  reviewed: false
  note: ""
```

- Change only `labels` (one line, comma-separated ids) and `note`. Leave `split`, `blind` and `reviewed` alone: `finalise` sets them.
- If you agree with the labels, do nothing and move on.
- **Topic ids** with their descriptions are in `taxonomy/topics.yaml`. Level 0 and level 1 are the topics with no parent, or whose parent has none.
- **More context:** the comment line has the DOI and DBLP links. `data/review/gold-context.md` (local only, because it holds abstracts) has the composite text (references, abstract, TLDR) of each work in the same order. Search it for the work ID (Cmd-F).
- **Check as you go:**

```bash
uv run flatatlas taxonomy check --gold taxonomy/proposals/gold-draft.yaml
```

This rejects unknown ids and labels deeper than level 1. The rules about parents and level-0 labels are checked by `gold finalise`.

## The 30 works I was least sure of

The position is the work's place in `gold-draft.yaml` (1 = first work).

| # | Work | Title | Draft labels | Why unsure |
|---|---|---|---|---|
| 11 | WIVLKT5CNWC | Factorization Forests | algebraic-language-theory, syntactic-monoids-and-varieties | Simon's semigroup tool; no level-1 topic is exactly about it |
| 12 | WKWH6MSRVSE | Syntactic Semiring and Universal Automaton | algebraic, syntactic-monoids-and-varieties, regular, nondeterministic-finite-automata | The universal automaton could be minimisation instead |
| 17 | WDV2SHFSCR7 | Using Acceptors as Transducers | machine-models, multi-head-and-multitape-automata, decision-problems, transducers | Is `transducers` warranted? |
| 25 | W6QC7S7UB6S | Weighted Prefix Normal Words | combinatorics-on-words, abelian-properties-of-words | Prefix normality has no topic; abelian is the nearest |
| 30 | WY6VD57SVX2 | Crystal Lattice Automata | implementation-and-applications | Chemistry application; nothing fits |
| 34 | W4UAOGCNDET | Synchronization of Communication | combinatorics-on-words, codes | Title only; a guess |
| 36 | WPOLXXW42Z3 | k-Local Graphs | combinatorics-on-words, pattern-languages | Graph data mining; weak fit |
| 47 | WBHM3ZB3OPC | Generalised Twinning Property | transducers, finite-state-transducers, weighted, weighted-automata | The weighted side (tropical monoids) may be incidental |
| 49 | WOOWCYSJNM6 | Mutually Accepting Capacitated Automata | machine-models, counter-automata, decision-problems | Capacitated automata have no topic |
| 56 | WHDR7GSQ2P6 | Complexity of q-fair languages | machine-models, automata-and-complexity-classes | Title only; I do not know what q-fair languages are |
| 133 | WLE75NVHQTE | Positive Varieties of Lattice Languages | algebraic, syntactic-monoids-and-varieties, weighted, weighted-automata | Are lattice-valued languages "weighted"? |
| 141 | WD6TG3R4IGD | Derick Wood: Always in Our Hearts | regular-languages | Obituary; any label is arbitrary |
| 144 | WO4DN7ICVBB | Embedding Words into Overlapping Tiles | algebraic-language-theory, automata-on-infinite-words | No level-1 topic fits |
| 170 | WMCE7MWUA6G | Alphabetic Complexity in Homomorphic Definitions | descriptional, picture-and-graph-languages, two-dimensional-languages | Alphabet size as a measure has no level-1 topic |
| 177 | WZU26YAKF7F | General Formal Systems | grammars, language-families | Title only; a guess |
| 185 | WQDGBGJHXPK | The Ehrenfeucht–Mycielski Sequence | combinatorics-on-words, factor-complexity-and-growth | No level-1 topic fits exactly |
| 201 | WKXPVSIWFNA | Mezei–Wright Theory on N-Subsets of an Algebra | algebraic, rational-and-recognisable-subsets, weighted, weighted-automata | The TLDR is a patent's; labelled from the title |
| 216 | WCQ42KLRMQR | On the Structure of Graphic DLI-Sets | grammars, language-families, combinatorics-on-words | I do not know what DLI-sets are |
| 223 | WF2PUJWYX75 | Involution Solid and Join Codes | combinatorics-on-words, codes, natural-computing, dna-computing-and-splicing | Is DNA word design enough for natural computing? |
| 225 | WDHD357GGZA | Bijective Binary Transducers | transducers, automata-on-infinite-words | Isometries of {0,1}^ω; automata-and-groups possible |
| 233 | WANBLM65BIS | Dolev–Yao Theory with Blindpair Operators | automata-for-verification | Protocol security; thin FLAT content |
| 257 | WJAOOQ2XTFG | Succinctness of Deterministic, …, Quantum Automata | four roots and four level-1 topics | Is the bridge too wide? |
| 273 | WAGRA5BLCLL | Adaptive Automata: a Revisited Proposal | machine-models | Self-modifying automata have no topic (also #332) |
| 278 | WJ3MNDUY5YK | Observational Equivalence and Bisimulation | concurrency-and-traces | Coalgebra; weak fit |
| 352 | WDJKO2GNKJX | An Algebraic-Geometric Public Key Cryptosystem | algebraic-language-theory | Title only in practice; probably out of scope |
| 379 | WMK7R2PV4VH | Descriptional Complexity of Soliton Automata | descriptional-complexity | Title only; no level-1 topic is sure |
| 405 | WLVBRV7MHIM | Recursive Word-Functions Without Concatenation | machine-models | Computability; no level-1 topic |
| 434 | WUPJVI4V6I7 | Hidden Grammars | grammars-and-context-free-languages | Title only; a guess |
| 449 | WLBEGTPA5ME | The Complexity of the Hanano Puzzle | machine-models, automata-and-complexity-classes | Puzzle NP-hardness; hardly FLAT |
| 456 | WCVKB3YXR7E | Visibly Pushdown Transducers | transducers, two-way-and-streaming-transducers, grammars, pushdown-automata | No level-1 topic for pushdown transducers |

Two near misses: #468 `WGURVFJGANC` (consensus game acceptors; no topic fits) and #470 `WNYJU4D2GB3` (Newton's method on semirings; `probabilistic-automata` possible). 161 works carry a note in all, and every note says why.

## What the draft already shows

These are numbers from my draft, not from your review. The report will give the final ones.

- **Split:** 341 train and 159 held out (31.8 %), set by the hash rule of P1-05.
- **Level-0 topics with fewer than 5 held-out works in the draft:** `grammatical-inference` (2), `automata-for-verification` (3), `quantum-computing-models` (4), `cellular-automata-and-symbolic-dynamics` (4). If that holds after review, the report lists them as too small to measure, as the session prompt allows.
- **Level-1 topics with fewer than 5 training works: 79 of 119.** Three are absent altogether: `automata-on-infinite-trees`, `word-representable-graphs` and `networks-of-evolutionary-processors`. A top-up of at most 100 works (PLAN §9.6) cannot bring 79 topics to 5 examples each, because that would need roughly 250 works. This is a question for after the review: raise the top-up cap, measure per-topic level-1 numbers only for the larger topics, or both. I have not changed anything.

## Top-up review (after the main review)

Your review of the 500 works changed no label, and `taxonomy/gold.yaml` holds them as reviewed. The 79 level-1 topics with fewer than 5 training works then got a top-up of 100 works. These are listed in `taxonomy/proposals/gold-topup.yaml`, with `sampling: topup`, and are training only: each one's hash split is `train`.

- **How they were found.** `flatatlas gold topup` searches pilot titles for the include phrases of each thin topic. It serves the topic with the fewest training works first, and takes candidates in a fixed random order.
- **What the notes say.** Each note starts with "Top-up: title matches …", the topics that brought the work in. My labels are drafted from the full composite text, so they can differ from those topics.
- **How to review.** Same as before: change `labels` or `note` where you disagree. The composite text is in `data/review/gold-topup-context.md`, in the same order.
- **Result.** By my labels the thin topics drop from 79 to 69. Most move to 3 or 4 training works. `automata-on-infinite-trees` stays at 0, because no pilot title matches it. Closing the gap fully would need a higher cap than D-61's 100 works.

## Time

About 2 hours for 500 works at about 15 s each. The works with notes take longer, and most of the others are quick confirmations.
