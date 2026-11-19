"""Pair features and labels: what the fusion model trains on and scores (PLAN §9.4).

A *pair* is a (work, topic) the shortlist kept, ancestors included. Each pair has the signal
scores, the work's context features, the topic's context features and two hierarchy features (the
strongest lexical and embedding evidence among the topic's descendants). The best-parent
probability is added by the fusion model itself, level by level.

Labels:

- **gold**: a work of ``gold.yaml`` with ``split: train``. For a level 0 or 1 topic the pair is
  positive when the topic is one of the work's labels and negative otherwise; deeper topics were
  not labelled, so those pairs have no gold label.
- **silver** (PLAN §9.4): works that are not in ``gold.yaml`` at all. Positive: ``lex_title`` is an
  exact-strength match and ``src_openalex`` agrees. Negative: the work is confidently in exactly one
  top-level topic and the pair's topic lies under another one. **Leak rule:** the two signals that
  defined a silver pair are hidden (NaN) in that pair's features.
- Held-out works never get a label.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from flatatlas.tagging.artefacts import Artefacts
from flatatlas.tagging.config import SIGNALS, TaggerConfig
from flatatlas.tagging.guard import Guard
from flatatlas.tagging.inputs import Corpus, Dag, Labels
from flatatlas.tagging.signals import WORK_FEATURES, Signals

TOPIC_FEATURES = ("t_level", "t_n_children", "t_seed_size", "t_seed_spread", "t_n_phrases")
HIERARCHY_FEATURES = ("child_lex", "child_emb")
# The decision model's two signals (PLAN §9.3, §9.5) come last, so the base model (every column
# before them) is the same model as before they existed. Raw probabilities: ``decide.calibrate``
# maps them, inside the fusion model, so a calibrator is never fitted on the works it scores.
DM_FEATURES = ("dm_l0", "dm_child")
BASE_FEATURES = (*SIGNALS, *WORK_FEATURES, *TOPIC_FEATURES, *HIERARCHY_FEATURES)
FEATURES = (*BASE_FEATURES, *DM_FEATURES)
N_BASE = len(BASE_FEATURES)
PARENT = "parent_p"
SILVER_DEFINING = ("lex_title", "src_openalex")  # the leak rule hides these in silver pairs

KIND_NONE, KIND_GOLD_RANDOM, KIND_GOLD_TOPUP, KIND_SILVER = 0, 1, 2, 3


@dataclass
class Pairs:
    work: np.ndarray  # corpus rows
    topic: np.ndarray  # DAG indexes
    candidate: np.ndarray  # True for shortlisted topics, False for ancestors added
    X: np.ndarray  # (n, len(FEATURES)) float32, NaN where absent
    p_noisy: np.ndarray
    label: np.ndarray  # int8: 1, 0, or -1 (no label)
    kind: np.ndarray  # int8, one of the KIND_ constants
    parents: list[list[int]]  # pair indexes of the topic's parents for the same work

    def __len__(self) -> int:
        return len(self.work)

    def subset(self, mask: np.ndarray) -> Pairs:
        """Rows ``mask``; parent links are kept only inside the subset (re-indexed)."""
        new = -np.ones(len(self), dtype=np.int64)
        keep = np.flatnonzero(mask)
        new[keep] = np.arange(len(keep))
        parents = [[int(new[p]) for p in self.parents[i] if new[p] >= 0] for i in keep]
        return Pairs(
            self.work[keep],
            self.topic[keep],
            self.candidate[keep],
            self.X[keep],
            self.p_noisy[keep],
            self.label[keep],
            self.kind[keep],
            parents,
        )


def hierarchy_matrices(sig: Signals, dag: Dag) -> tuple[np.ndarray, np.ndarray]:
    """Per (work, topic): the best lexical / embedding evidence among the topic's descendants."""
    m = sig.matrices
    lex = np.nan_to_num(
        np.maximum.reduce([m["lex_title"], m["lex_abstract"], m["lex_refs"]]), nan=0.0
    )
    emb = np.nan_to_num(m["emb_seed"], nan=0.0)
    child_lex = np.zeros_like(lex)
    child_emb = np.zeros_like(emb)
    for t in range(dag.n):
        desc = dag.descendants(t)
        if desc:
            child_lex[:, t] = lex[:, desc].max(axis=1)
            child_emb[:, t] = emb[:, desc].max(axis=1)
    return child_lex, child_emb


def build_pairs(
    sig: Signals,
    art: Artefacts,
    dag: Dag,
    corpus: Corpus,
    labels: Labels,
    closed: np.ndarray,
    candidates: np.ndarray,
    p_noisy: np.ndarray,
    cfg: TaggerConfig,
) -> Pairs:
    rows, topics = np.nonzero(closed)
    child_lex, child_emb = hierarchy_matrices(sig, dag)
    columns: list[np.ndarray] = []
    for name in SIGNALS:
        columns.append(sig.matrices[name][rows, topics])
    for name in WORK_FEATURES:
        columns.append(sig.work[name][rows])
    for name in TOPIC_FEATURES:
        columns.append(art.topic_features[name][topics])
    columns.append(child_lex[rows, topics])
    columns.append(child_emb[rows, topics])
    columns.extend(np.full(len(rows), np.nan) for _ in DM_FEATURES)  # filled by decide.features
    X = np.column_stack(columns).astype(np.float32)

    index = {(int(r), int(t)): i for i, (r, t) in enumerate(zip(rows, topics, strict=True))}
    parents: list[list[int]] = []
    for r, t in zip(rows, topics, strict=True):
        ps = [
            index[(int(r), p)]
            for p in dag.parents[int(t)]
            if dag.level[p] < dag.level[int(t)] and (int(r), p) in index
        ]
        parents.append(ps)

    label = -np.ones(len(rows), dtype=np.int8)
    kind = np.zeros(len(rows), dtype=np.int8)
    guard = Guard(labels.gold)
    for w, split in labels.split.items():
        row = corpus.index.get(w)
        if row is None or split != "train":
            continue
        sel = np.flatnonzero((rows == row) & (dag.level[topics] <= 1))
        gold_topics = {dag.index[x] for x in labels.by_work[w] if x in dag.index}
        for i in sel:
            label[i] = 1 if int(topics[i]) in gold_topics else 0
            kind[i] = KIND_GOLD_RANDOM if labels.sampling[w] == "random" else KIND_GOLD_TOPUP
    pairs = Pairs(
        rows, topics, candidates[rows, topics], X, p_noisy[rows, topics], label, kind, parents
    )
    assign_silver(pairs, sig, dag, corpus, labels, cfg)
    train_rows = {int(r) for r in pairs.work[pairs.label >= 0]}
    guard.check([corpus.work_ids[r] for r in train_rows], purpose="training pairs")
    return pairs


def assign_silver(
    pairs: Pairs, sig: Signals, dag: Dag, corpus: Corpus, labels: Labels, cfg: TaggerConfig
) -> None:
    """Add silver labels to the pairs of works that are not in ``gold.yaml`` (in place)."""
    roots: list[set[int]] = []
    for t in range(dag.n):
        anc = [a for a in dag.ancestors[t] if not dag.parents[a]]
        roots.append(set(anc) if anc else {t})
    s = cfg.silver
    min_src = cfg.signals.openalex_min_score
    title = np.nan_to_num(sig.matrices["lex_title"], nan=0.0)
    src = np.nan_to_num(sig.matrices["src_openalex"], nan=0.0)
    lexical_any = np.nan_to_num(
        np.maximum.reduce([sig.matrices[k] for k in ("lex_title", "lex_abstract", "lex_refs")]),
        nan=0.0,
    )
    gold_rows = {corpus.index[w] for w in labels.by_work if w in corpus.index}
    candidates: dict[str, list[int]] = {"pos": [], "neg": []}
    by_work: dict[int, list[int]] = {}
    for i, r in enumerate(pairs.work):
        by_work.setdefault(int(r), []).append(i)
    for r, idxs in by_work.items():
        if r in gold_rows:
            continue
        conf_roots: set[int] = set()
        any_roots: set[int] = set()
        for t in range(dag.n):
            if title[r, t] >= s.positive_min_title:
                conf_roots |= roots[t]
            if title[r, t] >= 0.3 or src[r, t] >= min_src or lexical_any[r, t] >= 0.5:
                any_roots |= roots[t]
        for i in idxs:
            t = int(pairs.topic[i])
            if title[r, t] >= s.positive_min_title and src[r, t] >= min_src:
                candidates["pos"].append(i)
            elif (
                len(conf_roots) == 1
                and any_roots == conf_roots
                and not (roots[t] & conf_roots)
                and title[r, t] < s.min_negative_gap
                and src[r, t] < s.min_negative_gap
            ):
                candidates["neg"].append(i)
    for name, idxs in candidates.items():
        keep = sorted(
            idxs,
            key=lambda i: hashlib.sha256(
                f"silver:{cfg.seed}:{corpus.work_ids[pairs.work[i]]}:{pairs.topic[i]}".encode()
            ).hexdigest(),
        )[: s.max_per_class]
        for i in keep:
            pairs.label[i] = 1 if name == "pos" else 0
            pairs.kind[i] = KIND_SILVER
            for col in SILVER_DEFINING:  # the leak rule
                pairs.X[i, FEATURES.index(col)] = np.nan
