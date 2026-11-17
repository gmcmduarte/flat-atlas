# Taxonomy v1: review guide (P1-06)

For Guilherme, before editing `taxonomy/topics.yaml` and `taxonomy/anchors.yaml`. Both files are
drafts: nothing carries `reviewed: true` yet. After your edits I mark the topics you touched or
approved as reviewed, run the checks and summarise your changes (P1-06 prompt).

## What is in the draft

| | |
|---|---|
| Topics | 181: 20 at level 0, 121 at level 1, 40 at level 2 |
| Status | all `active` (every topic has pilot evidence; none is `proposed`) |
| Multi-parent topics | 23 (listed below) |
| Phrases | every topic has at least 3 include phrases and 2 to 5 seed works from the pilot |
| Anchors | 272: 154 pilot (all in the corpus), 118 classics; all 272 verified |
| Venue expectations | `config/venues.yaml`, `expected_topics` for all five pilot venues |
| Checks | `uv run flatatlas taxonomy check` and `uv run flatatlas taxonomy anchors` pass |

How it was made: the 354 candidates of `taxonomy/proposals/v1.yaml`, the CCS, MSC and OpenAlex
seeds, and a reading of all 2,333 pilot titles. Single-word candidates ("deterministic",
"alphabet", "letters", "properties", "runs") are dissolved: their phrases moved into real topics
or were dropped. Acronyms are aliases of their long forms (`dfa` → Deterministic finite automata,
`nfa` → Nondeterministic finite automata). Names and descriptions are in our own words; CCS and
MSC appear only as codes in `xref`.

A rough check, not the tagger: matching each topic's phrases against pilot **titles** only, 2,040
of the 2,333 works (87 %) hit at least one topic. The misses are mostly obituaries and surveys
("In Memoriam Sheng Yu"), puzzles, and titles that name a technique and not a topic.

## The top-level cut (20 topics)

| Level 0 | id | Level-1 children | Level 2 below them |
|---|---|---|---|
| Finite automata and regular languages | `regular-languages` | 9 | 17 |
| Grammars and context-free languages | `grammars-and-context-free-languages` | 6 | 8 |
| Regulated rewriting, grammar systems and string rewriting | `rewriting-systems` | 7 | 3 |
| Descriptional complexity | `descriptional-complexity` | 6 | 7 |
| Operations on languages | `operations-on-languages` | 6 | 0 |
| Algebraic theory of languages and automata | `algebraic-language-theory` | 9 | 0 |
| Logic and automata | `logic-and-automata` | 6 | 0 |
| Automata on infinite words and games | `automata-on-infinite-words` | 5 | 2 |
| Automata for verification | `automata-for-verification` | 6 | 2 |
| Weighted and probabilistic automata | `weighted-and-probabilistic-automata` | 6 | 1 |
| Machine models and computational power | `machine-models` | 12 | 0 |
| Transducers and transductions | `transducers` | 3 | 1 |
| Tree languages and tree automata | `tree-languages` | 5 | 2 |
| Picture, array and graph languages | `picture-and-graph-languages` | 5 | 0 |
| Combinatorics on words | `combinatorics-on-words` | 17 | 1 |
| Cellular automata, symbolic dynamics and tilings | `cellular-automata-and-symbolic-dynamics` | 4 | 0 |
| Natural computing | `natural-computing` | 9 | 1 |
| Grammatical inference | `grammatical-inference` | 5 | 0 |
| Implementation and applications of automata | `implementation-and-applications` | 8 | 0 |
| Concurrency: traces, Petri nets and communicating automata | `concurrency-and-traces` | 3 | 0 |

(Children counted with all their parents, so a multi-parent topic appears under each.)

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
`concurrency-and-traces` MSC 68Q85). Three have no scheme node but are clear in the pilot:
`descriptional-complexity` (DCFS's subject), `operations-on-languages`, and
`implementation-and-applications` (CIAA's subject). `picture-and-graph-languages` groups the
two-dimensional and graph traditions, which are small separately.

**Cross-cutting facets are not level-0 topics.** "Decision problems", "complexity of problems",
"unary alphabets" and "surveys" cut across every area. As level-0 topics they would be attached
to half of all works and would blur the labelled set. Where a facet is a real community it is a
level-1 topic inside the area (`decision-problems-for-finite-automata`, `unary-languages`,
`automata-and-complexity-classes`).

## The ten decisions I am least sure of

1. **`rewriting-systems` as its own root.** Regulated rewriting, grammar systems, contextual
   grammars, L systems and string rewriting could be level-1 topics under
   `grammars-and-context-free-languages`. I split them because they form a distinct
   (Păun / Dassow / Rozenberg) community with 112 title hits in the pilot, and the grammar root
   would otherwise have 11 children. Merge them if you see one field.
2. **Decision problems only as a facet of finite automata.** There is
   `decision-problems-for-finite-automata`, but for context-free languages the decision problems
   sit inside `context-free-grammars`, and for other models inside the model's topic.
3. **Quantum automata** sit under `machine-models` and `weighted-and-probabilistic-automata`, not
   at level 0 (33 title hits in the pilot; small outside it).
4. **One root for cellular automata, symbolic dynamics and tilings.** These are three
   communities that share methods and authors in DLT. Split if cellular automata deserve their
   own bubble on the map (they will when AUTOMATA papers are added).
5. **`implementation-and-applications` holds string matching, regular-expression engines and
   finite-state NLP.** String matching could go under combinatorics on words; NLP could be a
   root. I kept CIAA's own framing.
6. **`concurrency-and-traces` is `active`** although the pilot has only 37 title hits. It is a
   recognised area (Mazurkiewicz traces, Petri-net languages) and will grow with new venues.
7. **Descriptional complexity against regular languages.** State complexity lives under
   `descriptional-complexity`; subregular classes under `regular-languages`. A paper on "state
   complexity of prefix-free languages" gets both: this is intended multi-labelling, but it is
   the most frequent pair in DCFS and the labeller will meet it often.
8. **`language-families` merges** the Chomsky hierarchy, context-sensitive and recursively
   enumerable languages and AFL theory. Context-sensitive languages alone had too few works for a
   level-1 topic.
9. **Kolmogorov complexity and algorithmic randomness** are under `descriptional-complexity`
   (the DCFS tradition), though they reach beyond FLAT.
10. **Level 1 has 121 topics**, at the top of the 60 to 120 the prompt asks for. Combinatorics on
    words alone has 17. Candidates to merge if you want fewer: `partial-words` into
    `repetitions-and-avoidability`; `word-representable-graphs` into `combinatorics-on-words`
    (no level 1); `automata-systems` into `multi-head-and-multitape-automata`;
    `reaction-systems` and `molecular-self-assembly` into one "other bio-inspired models".

## Topics hard to tell apart (for the labelled set)

- `deterministic-finite-automata` / `minimisation-of-automata` / `synchronizing-automata`: all
  about DFAs; the descriptions say which question each one is about.
- `state-complexity-of-operations` / `conversions-and-trade-offs`: the result of an operation
  against the cost of changing the kind of description.
- `star-free-languages` / `testable-languages` / `syntactic-monoids-and-varieties`: specific
  classes against the general theory.
- `repetitions-and-avoidability` / `periodicity-and-borders` / `abelian-properties-of-words`.
- `weighted-automata` / `probabilistic-automata` / `cost-and-distance-automata`.
- `counter-automata` / `storage-automata` / `multi-head-and-multitape-automata`.

## Multi-parent topics (all intentional)

`nfa-reduction` (minimisation, NFAs) · `multi-pushdown-automata` (pushdown, infinite-state
verification) · `lindenmayer-systems` (rewriting, natural computing) · `size-of-two-way-automata`
(trade-offs, two-way automata) · `size-of-regular-expressions` (trade-offs, regular expressions)
· `syntactic-complexity` (descriptional complexity, algebraic theory) ·
`complexity-of-grammars-and-systems` (descriptional complexity, rewriting) ·
`shuffle-and-interleaving` (operations, combinatorics on words) ·
`insertion-and-deletion-operations` (operations, natural computing) · `star-free-languages`
(algebraic theory, logic) · `testable-languages` (algebraic theory, subregular classes) ·
`temporal-logics` (logic, verification) · `infinite-games` (infinite words, verification) ·
`weighted-logics` (weighted automata, logic) · `quantum-automata` (machine models, weighted and
probabilistic) · `weighted-transducers` (finite-state transducers, weighted automata) ·
`tree-transducers` (transducers, tree languages) · `weighted-tree-automata` (tree languages,
weighted) · `automata-on-infinite-trees` (tree languages, infinite words) · `codes`
(combinatorics on words, algebraic theory) · `pattern-languages` (combinatorics on words,
grammatical inference) · `insertion-deletion-systems` (natural computing, rewriting) ·
`regex-engines` (implementation, regular expressions).

## Shallow areas

Level 1 only, no level 2, and few pilot works (fewer than 6 title hits): `automata-on-infinite-trees`,
`automata-and-neural-networks`, `learning-grammars-and-trees`, `cost-and-distance-automata`,
`supervisory-control`, `kleene-algebra`, `reaction-systems`. Whole roots with no level 2:
operations on languages, algebraic theory, logic, machine models, picture and graph languages,
cellular automata, grammatical inference, implementation, concurrency. The pilot (DLT, CIAA,
DCFS) is light on verification, logic, infinite words and natural computing; these areas will
deepen when their venues (CONCUR, LICS, CMC, UCNC, AUTOMATA, ...) are added.

## Anchors

- 154 **pilot** anchors, about one per level-1 and level-2 topic, chosen as titles that name
  their topic plainly. Each has its DBLP key and DOI (where it has one) from the warehouse.
- 118 **classic** anchors across the whole field. Identifiers were found by
  `flatatlas taxonomy anchors --find` (title match in the local DBLP dump, then OpenAlex title
  search; 23 searches, USD 0.023) and verified by `flatatlas taxonomy anchors` (DOI against
  OpenAlex, DBLP key against the warehouse or the dump; the title must match).
- Dropped: **Büchi 1962** ("On a decision method in restricted second order arithmetic", PLAN
  §9.6's own example): it has no DOI and no DBLP record. McNaughton 1966 anchors `omega-automata`
  instead.
- Notes the check prints (not failures): OpenAlex gives other years for three works (the WIA 1999
  volume printed in 2001; Kondacs and Watrous 1997 as 2002; Badr, Geffert and Shipman 2009 as 2007);
  DBLP lists Brüggemann-Klein and Wood 1998 twice with two DOIs (the first record is used);
  Vardi and Wolper 1986 has a DBLP key and no DOI.
- No classic anchor is in the pilot corpus (they appeared in journals or at other venues). The
  "≥ 90 % of anchors present in the corpus hit" check of PLAN §9.6 therefore uses the 154 pilot
  anchors for now.

## How to edit

- **Rename a topic:** change `name` freely. Changing `id` also needs the same change in
  `anchors.yaml` (`topic:`), in `config/venues.yaml` (`expected_topics`) and in other topics'
  `parents`. The check reports every dangling reference.
- **Merge two topics:** keep one, move the other's `aliases`, `include_phrases` and `seed_works`
  into it, point its children's `parents` at the survivor, and delete it. Aliases must stay
  unique across all topics.
- **Delete a topic:** re-parent or delete its children first. To keep an id from coming back,
  set `status: deprecated` instead of deleting it.
- **Move a topic:** edit `parents`. Several parents are allowed; the level is the shortest path to
  a root. A topic with `parents: []` becomes a root.
- **Phrases:** plain strings, matched after folding case, accents and hyphens. Two siblings may
  not share a phrase unless every use carries a context, written
  `{phrase: "aperiodic", context: ["monoid", "semigroup"]}`. `exclude_phrases` lists false
  friends ("card shuffl").
- **Status:** `active` (default), `proposed` (shown as tentative), `deprecated`.
- **Anchors:** change `topic` to re-target one, delete lines to drop it. To add one, write `id`,
  `title`, `year`, `topic`, `kind` without identifiers, run
  `uv run flatatlas taxonomy anchors --find`, copy the DOI or DBLP key it proposes, then run
  `uv run flatatlas taxonomy anchors` (add `--offline` to use cached answers only).
- **After every edit:** `uv run flatatlas taxonomy check`. Once the files are committed with
  `reviewed: true`, the check refuses changes to those entries unless you pass
  `--allow-reviewed-edits` (CLAUDE.md rule 6).

When you are done, tell me which topics you approved without changes and which you edited; I set
`reviewed: true` on both groups.
