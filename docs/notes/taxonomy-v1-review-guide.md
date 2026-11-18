# Taxonomy v1: review guide (P1-06)

The record of how `taxonomy/topics.yaml` and `taxonomy/anchors.yaml` were drafted and reviewed.
Round 1 (2026-11-17) was Claude's draft. In round 2 (2026-11-18) Guilherme decided two of the
open questions (decision problems made general; quantum a root) and asked Claude to answer the
rest, review the names and descriptions, the level-2 topics, the phrases and every anchor. Nothing
carries `reviewed: true` until Guilherme approves.

## What is in the files

| | |
|---|---|
| Topics | 181: 21 at level 0, 119 at level 1, 41 at level 2 |
| Status | all `active` (every topic has pilot evidence; none is `proposed`) |
| Multi-parent topics | 24 (listed below) |
| Phrases | every topic has at least 3 include phrases and 2 to 5 seed works from the pilot |
| Anchors | 278: 157 pilot (all in the corpus), 121 classics; all 278 verified |
| Venue expectations | `config/venues.yaml`, `expected_topics` for all five pilot venues |
| Checks | `uv run flatatlas taxonomy check` and `uv run flatatlas taxonomy anchors` pass |

Sources: the 354 candidates of `taxonomy/proposals/v1.yaml`, the CCS, MSC and OpenAlex seeds, and
a reading of all 2,333 pilot titles. Names and descriptions are in our own words; CCS and MSC
appear only as codes in `xref`.

**Rough lexical coverage** (the include phrases matched on each work's own text: title, abstract
and TLDR; not the tagger): 2,186 of 2,333 works (94 %) hit some topic, 2,018 some level-1 topic.
The misses are mostly obituaries, puzzles and titles that name a technique and not a topic.

## The top-level cut (21 topics)

| Level 0 | id | Level-1 children | Level 2 below them |
|---|---|---|---|
| Finite automata and regular languages | `regular-languages` | 9 | 17 |
| Grammars and context-free languages | `grammars-and-context-free-languages` | 7 | 8 |
| Rewriting systems and regulated grammars | `rewriting-systems` | 7 | 3 |
| Descriptional complexity | `descriptional-complexity` | 6 | 7 |
| Operations on languages | `operations-on-languages` | 6 | 0 |
| Algebraic theory of languages and automata | `algebraic-language-theory` | 9 | 0 |
| Logic and automata | `logic-and-automata` | 6 | 0 |
| Automata on infinite words and games | `automata-on-infinite-words` | 5 | 2 |
| Automata for verification | `automata-for-verification` | 6 | 2 |
| Weighted and probabilistic automata | `weighted-and-probabilistic-automata` | 4 | 1 |
| Machine models and computational power | `machine-models` | 12 | 0 |
| Quantum automata and quantum models of computation | `quantum-computing-models` | 2 | 0 |
| Transducers and transductions | `transducers` | 3 | 1 |
| Tree languages and tree automata | `tree-languages` | 5 | 2 |
| Picture, array and graph languages | `picture-and-graph-languages` | 5 | 0 |
| Combinatorics on words | `combinatorics-on-words` | 16 | 2 |
| Cellular automata, symbolic dynamics and tilings | `cellular-automata-and-symbolic-dynamics` | 4 | 0 |
| Natural computing | `natural-computing` | 9 | 1 |
| Grammatical inference | `grammatical-inference` | 4 | 0 |
| Implementation and applications of automata | `implementation-and-applications` | 8 | 0 |
| Concurrency: traces, Petri nets and communicating automata | `concurrency-and-traces` | 3 | 0 |

(Children counted under each of their parents, so a multi-parent topic appears more than once.)

**Why this cut.** Each level-0 topic is a community a FLAT researcher would name: it has its own
textbooks or survey chapters and its own sessions at DLT, CIAA or DCFS, and most match a CCS node
or an MSC code (`regular-languages` CCS Regular languages; `grammars-and-context-free-languages`
CCS Grammars and context-free languages; `rewriting-systems` CCS Rewrite systems, MSC 68Q42;
`algebraic-language-theory` CCS Algebraic language theory, MSC 68Q70 and 20M35;
`logic-and-automata` MSC 03D05; `automata-on-infinite-words` CCS Automata over infinite objects;
`automata-for-verification` MSC 68Q60; `weighted-and-probabilistic-automata` CCS Quantitative
automata; `machine-models` CCS Automata extensions; `transducers` CCS Transducers; `tree-languages`
CCS Tree languages; `combinatorics-on-words` MSC 68R15; `cellular-automata-and-symbolic-dynamics`
MSC 68Q80 and 37B10; `natural-computing` MSC 68Q07; `grammatical-inference` MSC 68Q32;
`concurrency-and-traces` MSC 68Q85). Four have no scheme node but are clear in the pilot or were
decided: `descriptional-complexity` (DCFS's subject), `operations-on-languages`,
`implementation-and-applications` (CIAA's subject) and `quantum-computing-models` (Guilherme's
decision). `picture-and-graph-languages` groups the two-dimensional and graph traditions, which are
small separately.

## The ten open questions: decisions

| # | Question | Decision | By | Reason |
|---|---|---|---|---|
| 1 | `rewriting-systems` as its own root? | **Keep**; renamed "Rewriting systems and regulated grammars" | Claude | A distinct community (regulated rewriting, grammar systems, contextual and L systems, Church–Rosser) with 141 works in the pilot; CCS separates Rewrite systems from Grammars and CFLs; merging would give the grammar root 14 children. The old name left out contextual grammars and L systems. |
| 2 | Decision problems only for finite automata? | **General**: `decision-problems`, "Decision problems and their complexity", one level-1 topic under `regular-languages`, `grammars-and-context-free-languages` and `machine-models` | Guilherme | Decision problems for CFGs, pushdown, counter and other machines belong there too. Kept at level 1 (not a root) because a facet root would attach to a third of all works. |
| 3 | Quantum automata: root or not? | **Root** `quantum-computing-models` with `quantum-finite-automata` and `quantum-branching-programs-and-queries` | Guilherme | |
| 4 | One root for cellular automata, symbolic dynamics and tilings? | **Keep together** | Claude | 73 pilot works in all; the three share authors and methods in DLT. Split when AUTOMATA papers are added (P2-01). |
| 5 | String matching and finite-state NLP under implementation? | **Keep** | Claude | CIAA's framing. Stringology proper is mostly outside FLAT; what the pilot holds is automata-based. |
| 6 | `concurrency-and-traces` active? | **Keep active** | Claude | 45 pilot works (traces, Petri-net languages, communicating automata); a recognised area that will grow with CONCUR-like venues. |
| 7 | State complexity / subregular double labelling? | **Keep** | Claude | Honest multi-labelling: "state complexity of prefix-free languages" is both. Listed below as a pair the labeller will meet often. |
| 8 | `language-families` merges context-sensitive, r.e. and AFL theory? | **Keep** | Claude | Context-sensitive languages alone hold too few works for a level-1 topic. |
| 9 | Kolmogorov complexity under descriptional complexity? | **Keep** | Claude | The DCFS tradition (Blum static complexity, randomness); 14 pilot works. |
| 10 | Level 1 at the top of 60 to 120? | **119** after two merges and one move | Claude | `learning-grammars-and-trees` and `learning-transducers-and-weighted-automata` merged into `learning-beyond-finite-automata` (10 works together); `cost-and-distance-automata` merged into `weighted-automata` (distance automata are weighted automata over min-plus); `partial-words` moved to level 2 (6 of its 8 works are also repetition papers). The quantum root added two level-1 topics. |

## Round-2 review: what changed

**Names and descriptions (levels 0 and 1).** All 140 read against their siblings. Changes:
the line breaks of the first draft had split hyphenated words in 11 descriptions ("self- verifying");
fixed. Boundaries now stated where two siblings share words: `supervisory-control` against
`infinite-games` (both say "synthesis"); `automata-systems` (cooperating automata, for power)
against `communicating-automata` (concurrency); `insertion-and-deletion-operations` (operations on
languages) against `insertion-deletion-systems` (generative systems); `finite-tree-automata`
(unweighted) against `weighted-tree-automata`; `context-free-grammars` no longer claims decision
problems.

**Level 2 (41 topics).** All are recognised subfields of their parents with 2 to 35 pilot works;
the thinnest are `parsing-expression-grammars` (2) and `spiking-neural-p-systems` (3), kept as named
formalisms. Only change: `partial-words` moved down from level 1.

**Phrases.** Every include phrase was matched against the pilot and, where it caught works that no
other phrase of its topic caught, the titles were read. 31 fixes in 26 topics:

- context words added to ambiguous phrases: "synchronization" (firing squad, synchronized grammars),
  "minimality", "self-verifying" (Büchi arithmetic predicates), "unambiguity" (morphisms), "most
  complex", "acyclic automata", "non-returning" (also a PC grammar-system mode), "acceptance
  conditions" (finite automata too), "verification" (interactive-proof verifiers), "neighborhood"
  (cellular-automaton neighbourhoods), "word problem" (string rewriting), "compressed" and
  "compression", "traces" (Szilard traces), "language recognition", "avoidance" (crowd dynamics),
  "morphic" (morphic characterisations);
- narrowed: "liveness" → "liveness properties", "infinite-state" → "infinite-state systems",
  "bisimilarity" → its decidability forms, "eilenberg" → "eilenberg correspondence" (not Eilenberg
  machines), "tree width" → "nondeterministic tree width", "greedy" → "greedy parsing",
  "environment" → "environment for";
- dropped as too generic: "grammars" (grammar root), "randomness", "circuits", "quantitative",
  "practical", "application", "images" (homomorphic images), "forests" (factorisation forests),
  "powers";
- new exclusions: "syntactic semiring" (weighted root), tiling-system terms (tilings), "abelian
  groups" (abelian words), "reversible cellular automata" (reversible automata).

**Anchors.** All read again for whether the title alone makes the topic clear.
`thatcher-wright-1968` moved from `finite-tree-automata` to `monadic-second-order-logic` (its
title names only second-order logic). Retargeted to the restructured topics: quantum (2),
learning (2), distance automata (2), decision problems (1). Added: Bertoni, Choffrut and
Radicioni 2009 (CFL inclusion, pilot) and Hunt, Rosenkrantz and Szymanski 1976, Stockmeyer and
Meyer 1973 (classics) for `decision-problems`; Ablayev et al. 2014 (quantum OBDDs, pilot);
Ambainis and Freivalds 1998 (classic) for `quantum-finite-automata`; Loff, Moreira and Reis 2018
(pilot) for `parsing-expression-grammars`, the only topic that had none. Every level-1 and level-2
topic now has at least one anchor.

## Topics hard to tell apart (for the labelled set)

From sibling overlap of phrase hits in the pilot:

- `deterministic-finite-automata` with `minimisation-of-automata` (45 % of the smaller set shared),
  `unary-languages` (38 %), `nondeterministic-finite-automata` (29 %).
- `context-free-grammars` with `mildly-context-sensitive-grammars` (43 %), `conjunctive-and-boolean-grammars`
  (35 %), `pushdown-automata`, `parsing` and `language-families` (29 % each).
- `decision-problems` with `counter-automata` and `storage-automata` (47 %): intended
  multi-labelling.
- `finite-tree-automata` with `weighted-tree-automata` (63 %).
- `monadic-second-order-logic` and `weighted-automata`, each with `weighted-logics` (55 %).
- `automata-from-regular-expressions` with `derivatives-of-regular-expressions` (36 %).
- `morphic-and-automatic-sequences` with `morphisms-and-pcp` (30 %).
- `repetitions-and-avoidability`, `periodicity-and-borders` and `abelian-properties-of-words`
  (26 % for each pair).
- At level 0, `regular-languages` overlaps every root (its phrases "finite automata" and "regular
  languages" occur in most abstracts); the strongest pairs are with `machine-models`,
  `descriptional-complexity` and `operations-on-languages`.

## Multi-parent topics (all intentional)

`decision-problems` (regular languages, grammars, machine models) · `nfa-reduction` (minimisation,
NFAs) · `multi-pushdown-automata` (pushdown, infinite-state verification) · `lindenmayer-systems`
(rewriting, natural computing) · `size-of-two-way-automata` (trade-offs, two-way automata) ·
`size-of-regular-expressions` (trade-offs, regular expressions) · `syntactic-complexity`
(descriptional complexity, algebraic theory) · `complexity-of-grammars-and-systems` (descriptional
complexity, rewriting) · `shuffle-and-interleaving` (operations, combinatorics on words) ·
`insertion-and-deletion-operations` (operations, natural computing) · `star-free-languages`
(algebraic theory, logic) · `testable-languages` (algebraic theory, subregular classes) ·
`temporal-logics` (logic, verification) · `infinite-games` (infinite words, verification) ·
`weighted-logics` (weighted automata, logic) · `weighted-transducers` (finite-state transducers,
weighted automata) · `tree-transducers` (transducers, tree languages) · `weighted-tree-automata`
(tree languages, weighted) · `automata-on-infinite-trees` (tree languages, infinite words) ·
`partial-words` (repetitions, periodicity) · `codes` (combinatorics on words, algebraic theory) ·
`pattern-languages` (combinatorics on words, grammatical inference) · `insertion-deletion-systems`
(natural computing, rewriting) · `regex-engines` (implementation, regular expressions).

## Shallow areas

Level-1 topics with 10 or fewer pilot works (own text): `automata-on-infinite-trees` (4),
`automata-and-neural-networks` (3), `supervisory-control` (5), `kleene-algebra` (7),
`reaction-systems` (7), `networks-of-evolutionary-processors` (6), `state-machine-testing` (6),
`word-representable-graphs` (7), `quantum-branching-programs-and-queries` (8),
`ciliate-gene-assembly` (8), `limited-automata` (9), `roots-powers-and-decompositions` (9),
`learning-regular-languages` (10), `learning-beyond-finite-automata` (10),
`dynamics-of-cellular-automata` (10). The pilot (DLT, CIAA, DCFS) is light on verification, logic,
infinite words, quantum and natural computing; these deepen when their venues are added.

## Anchors

- 157 **pilot** anchors, at least one per level-1 and level-2 topic, chosen as titles that name
  their topic plainly; DBLP key and DOI (where one exists) from the warehouse.
- 121 **classic** anchors across the field. Identifiers found by
  `flatatlas taxonomy anchors --find` (title match in the local DBLP dump, then OpenAlex title
  search) and verified by `flatatlas taxonomy anchors` (DOI against OpenAlex, DBLP key against the
  warehouse or the dump; the title must match).
- Dropped: **Büchi 1962** ("On a decision method in restricted second order arithmetic", PLAN
  §9.6's own example) has no DOI and no DBLP record. McNaughton 1966 anchors `omega-automata`.
- Notes the check prints (not failures): OpenAlex gives other years for four works (the WIA 1999
  volume printed in 2001; Kondacs and Watrous 1997 as 2002; Ambainis and Freivalds 1998 as 2002;
  Badr, Geffert and Shipman 2009 as 2007). DBLP lists Brüggemann-Klein and Wood 1998 twice with two
  DOIs (the first record is used). Vardi and Wolper 1986 has a DBLP key and no DOI.
- No classic anchor is in the pilot corpus, so PLAN §9.6's "≥ 90 % of anchors present in the
  corpus hit" check uses the 157 pilot anchors for now.

## How to edit

- **Rename a topic:** change `name` freely. Changing `id` also needs the same change in
  `anchors.yaml` (`topic:`), `config/venues.yaml` (`expected_topics`) and other topics' `parents`;
  the check reports every dangling reference.
- **Merge two topics:** keep one, move the other's `aliases`, `include_phrases` and `seed_works`
  into it, point its children's `parents` at the survivor, and delete it. Aliases stay unique.
- **Delete a topic:** re-parent or delete its children first, or set `status: deprecated`.
- **Move a topic:** edit `parents`. Several parents are allowed; the level is the shortest path to
  a root. `parents: []` makes a root.
- **Phrases:** plain strings, matched after folding case, accents and hyphens. Two siblings may
  not share a phrase unless every use carries a context: `{phrase: "aperiodic", context:
  ["monoid", "semigroup"]}`. `exclude_phrases` lists false friends.
- **Anchors:** change `topic` to re-target, delete lines to drop. To add one, write `id`, `title`,
  `year`, `topic`, `kind` without identifiers, run `uv run flatatlas taxonomy anchors --find`, copy
  the DOI or DBLP key it proposes, then run `uv run flatatlas taxonomy anchors`.
- **After every edit:** `uv run flatatlas taxonomy check`. Once committed with `reviewed: true`,
  entries cannot change without `--allow-reviewed-edits` (CLAUDE.md rule 6).
