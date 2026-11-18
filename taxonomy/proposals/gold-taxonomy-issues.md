# Taxonomy issues found while drafting the labelled set (P1-06b)

These are proposals only: `taxonomy/topics.yaml` is reviewed and was not edited (CLAUDE.md rule 6). I judged none of them serious enough to stop the labelling. Each affects a handful of the 450 drafted works, and the level-0 labels carry those works. They are for the next taxonomy version, or for Guilherme to overrule.

## 1. `decision-problems` cannot follow some models

`decision-problems` has three parents: `regular-languages`, `grammars-and-context-free-languages` and `machine-models`. Papers deciding properties of other models cannot take it unless one of those roots is also labelled. In the draft:

| Model | Work |
|---|---|
| regulated rewriting | `WQR7EIV4BMN` (membership for unordered vector grammars) |
| operations on languages | `WLWEUW7IZZ3` (an undecidable problem for shuffle languages) |
| tree grammars | `WEM5WKPADL5` (decision problems on rigid tree grammars) |
| linear orderings | `WDZEII6WWOK` (emptiness of automata on linear orderings) |

The tagger's recall on `decision-problems` will look better than it is, because these works never count against it. **Proposal:** either add parents (`rewriting-systems`, `tree-languages`, `automata-on-infinite-words`), or state in the topic description that it covers only the three roots.

## 2. Level-1 gaps (no topic fits; the work keeps a level-0 label only, or the nearest topic)

- **Weighted grammars:** `WHFNST5EVNJ`. **Pushdown or visibly pushdown transducers:** `WCVKB3YXR7E`.
- **Collage and grid picture grammars:** `WGSHAGNEZC2`, `WF7BP3LQ7FJ`. `fractals-and-images` was used as the nearest topic.
- **Adaptive or self-modifying automata:** `WAGRA5BLCLL`, `W7IHCHVTL7A`.
- **State complexity of fixed classes or languages, not of operations:** `WIMSRIUIY3K`, `W5IAJN4MHZV`, `WMCE7MWUA6G`, `WP42CPGHC66`. Descriptional complexity has no level-1 topic for "the size of a class" or for new size measures.
- **Machine-learning applications of weighted automata (rational kernels):** `WMNRRJCDG2F`, `WSN6OORK4ZA`. Implementation and applications has no level-1 topic for them.
- **Circuits and hazard algebra:** `WICRAEBPM3X`, `WSMOU4UGIXV`, `WE4MFUPVKTQ`.

None of these gaps holds enough pilot works to justify a topic now. Recheck when venues are added (P2-01).

## 3. `unary-languages` sits under `regular-languages` only

Unary questions about non-regular devices cannot use the topic, for example forgetting automata (`WPOE2NSEZKW`) and unary language equations (`WX46V5VOIDP`). **Proposal:** add `machine-models` as a parent, or accept the limit.

## 4. Out-of-scope works are forced to take a level-0 label

The pilot holds a few works that are hardly FLAT: obituaries, a puzzle-complexity paper, a cryptosystem, software metrics and circuit algebra. `gold.yaml` requires a level-0 label, so each one gets the nearest root. This is a scope question for P2-02 rather than a taxonomy one. It is recorded here because it adds noise to the labelled set.

## 5. Not a taxonomy problem, but related: thin level-1 topics

83 of the 119 level-1 topics have fewer than 5 training works in the draft. The fault is not the topics but the ratio: 119 topics against 500 random works. The top-up cap of 100 works (PLAN §9.6, D-61) cannot close the gap. The review guide lists the options.
