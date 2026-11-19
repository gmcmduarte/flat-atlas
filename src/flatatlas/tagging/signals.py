"""The signals of cascade step 1 (PLAN §9.3): one score per (work, topic), all free.

``lex_title``, ``lex_abstract``, ``lex_refs``, ``emb_seed``, ``emb_desc``, ``src_openalex`` and
``venue_prior``, read from the composite text parts of P1-05 (``flatatlas.text.composite``). Each
signal is a dense ``(works, topics)`` float32 matrix. Where a signal does not exist for a pair (no
abstract, no reference titles, a topic without seeds or an OpenAlex mapping) the cell is NaN, so a
model can tell "absent" from "zero". Embedding signals are per-topic percentiles, never raw
cosines (PLAN §9.3).

Also here: the per-work context features (``has_abstract``, ``n_references``, ...), which the
fusion model uses to learn when to trust each signal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from flatatlas.tagging.artefacts import Artefacts
from flatatlas.tagging.config import SIGNALS, TaggerConfig
from flatatlas.tagging.inputs import Corpus, Dag, Labels
from flatatlas.tagging.matcher import Match, Matcher, context_tokens, tokenise
from flatatlas.text.composite import CompositeParts

WORK_FEATURES = (
    "has_abstract",
    "has_tldr",
    "n_references",
    "n_references_with_title",
    "emb_source_s2",
    "title_tokens",
    "decade",
)


@dataclass
class Signals:
    matrices: dict[str, np.ndarray]  # signal name -> (works, topics) float32
    work: dict[str, np.ndarray]  # context feature -> (works,) float32


def percentile(reference: np.ndarray, scores: np.ndarray) -> np.ndarray:
    """Share of the sorted ``reference`` that is at or below each score."""
    if len(reference) == 0:
        return np.full(scores.shape, np.nan, dtype=np.float32)
    return (np.searchsorted(reference, scores, side="right") / len(reference)).astype(np.float32)


def work_features(parts: list[CompositeParts], emb_source: np.ndarray) -> dict[str, np.ndarray]:
    def arr(values) -> np.ndarray:
        return np.asarray(list(values), dtype=np.float32)

    return {
        "has_abstract": arr(bool(p.abstract) for p in parts),
        "has_tldr": arr(bool(p.tldr) for p in parts),
        "n_references": arr(p.n_references for p in parts),
        "n_references_with_title": arr(p.n_references_with_title for p in parts),
        "emb_source_s2": emb_source.astype(np.float32),
        "title_tokens": arr(len(tokenise(p.title)) for p in parts),
        "decade": arr((int(p.year) // 10 - 190) if p.year else np.nan for p in parts),
    }


# -- lexical signals -------------------------------------------------------------------------------


def _best_by_topic(matches: list[Match], vetoed: set[int]) -> dict[int, float]:
    best: dict[int, float] = {}
    for m in matches:
        t = m.entry.topic
        if t not in vetoed and m.entry.weight > best.get(t, 0.0):
            best[t] = m.entry.weight
    return best


def lexical_row(
    include: Matcher, exclude: Matcher, part: CompositeParts, scale: float
) -> tuple[dict[int, float], dict[int, float] | None, dict[int, float] | None]:
    """``(title, abstract, refs)`` scores of one work as ``{topic: score}``.

    The abstract and refs entries are None when the work has no abstract/TLDR or no reference
    titles. An exclude phrase vetoes a topic's matches within the same field.
    """
    title_tokens = tokenise(part.title)
    abstract_text = " ".join(x for x in (part.abstract, part.tldr) if x)
    abstract_tokens = tokenise(abstract_text) if abstract_text else []
    own_context = context_tokens(part.title, abstract_text)

    title_scores = _best_by_topic(
        include.find(title_tokens, own_context),
        {m.entry.topic for m in exclude.find(title_tokens)},
    )

    abstract_scores: dict[int, float] | None = None
    if abstract_tokens:
        vetoed = {m.entry.topic for m in exclude.find(abstract_tokens)}
        per_topic: dict[int, dict[int, float]] = {}
        for m in include.find(abstract_tokens, own_context):
            t = m.entry.topic
            if t in vetoed:
                continue
            spans = per_topic.setdefault(t, {})
            spans[m.start] = max(spans.get(m.start, 0.0), m.entry.weight)
        per100 = 100.0 / len(abstract_tokens)
        abstract_scores = {
            t: 1.0 - math.exp(-sum(spans.values()) * per100 / scale)
            for t, spans in per_topic.items()
        }

    refs_scores: dict[int, float] | None = None
    if part.reference_titles:
        totals: dict[int, float] = {}
        for ref in part.reference_titles:
            toks = tokenise(ref)
            ctx = frozenset(toks)
            vetoed = {m.entry.topic for m in exclude.find(toks)}
            for t, w in _best_by_topic(include.find(toks, ctx), vetoed).items():
                totals[t] = totals.get(t, 0.0) + w
        n = len(part.reference_titles)
        refs_scores = {t: v / n for t, v in totals.items()}
    return title_scores, abstract_scores, refs_scores


def lexical_matrices(
    art: Artefacts, corpus: Corpus, dag: Dag, cfg: TaggerConfig
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n, t = len(corpus), dag.n
    title = np.zeros((n, t), dtype=np.float32)
    abstract = np.full((n, t), np.nan, dtype=np.float32)
    refs = np.full((n, t), np.nan, dtype=np.float32)
    scale = cfg.signals.lex_abstract_scale
    for row, part in enumerate(corpus.parts):
        ts, abs_s, refs_s = lexical_row(art.include, art.exclude, part, scale)
        for topic, v in ts.items():
            title[row, topic] = v
        if abs_s is not None:
            abstract[row] = 0.0
            for topic, v in abs_s.items():
                abstract[row, topic] = v
        if refs_s is not None:
            refs[row] = 0.0
            for topic, v in refs_s.items():
                refs[row, topic] = v
    return title, abstract, refs


# -- embedding, source and prior signals -------------------------------------------------------


def embedding_matrices(art: Artefacts, corpus: Corpus, dag: Dag) -> tuple[np.ndarray, np.ndarray]:
    n = len(corpus)
    rows = np.arange(n)
    seed = np.full((n, dag.n), np.nan, dtype=np.float32)
    for t in range(dag.n):
        c = art.centroids[t]
        if c is not None:
            seed[:, t] = percentile(art.ref_seed[t], c.scores(corpus.vectors, rows))
    work_vecs = art.desc_work if art.desc_work is not None else corpus.vectors
    cos = work_vecs @ art.desc_topic.T
    desc = np.empty((n, dag.n), dtype=np.float32)
    for t in range(dag.n):
        desc[:, t] = percentile(art.ref_desc[t], cos[:, t])
    return seed, desc


def source_matrix(art: Artefacts, corpus: Corpus, dag: Dag, min_score: float) -> np.ndarray:
    """OpenAlex's own score for the best mapped OpenAlex topic; NaN where there is no mapping."""
    out = np.full((len(corpus), dag.n), np.nan, dtype=np.float32)
    mapped = [t for t in range(dag.n) if art.oa_topics[t]]
    for row, topics in enumerate(corpus.openalex):
        if not topics:
            continue
        for t in mapped:
            scores = [topics.get(o, 0.0) for o in art.oa_topics[t]]
            best = max(scores)
            out[row, t] = best if best >= min_score else 0.0
    return out


def venue_matrix(
    art: Artefacts, corpus: Corpus, dag: Dag, labels: Labels, smoothing: float
) -> np.ndarray:
    """Share of the venue's random training works with the topic (the work itself left out).

    Only levels 0 and 1 are labelled, so deeper topics are NaN.
    """
    out = np.full((len(corpus), dag.n), np.nan, dtype=np.float32)
    base = art.base_rate
    labelled = dag.level <= 1
    for row, w in enumerate(corpus.work_ids):
        v = corpus.venues[row]
        counts = art.venue_counts.get(v)
        if counts is None:
            continue
        n = art.venue_n[v]
        own = np.zeros(dag.n)
        if labels.split.get(w) == "train" and labels.sampling.get(w) == "random":
            n -= 1
            for label in labels.by_work[w]:
                if label in dag.index:
                    own[dag.index[label]] = 1
        prior = (counts - own + smoothing * base) / (max(n, 0) + smoothing)
        out[row, labelled] = prior[labelled]
    return out


def compute_signals(
    art: Artefacts, corpus: Corpus, dag: Dag, labels: Labels, cfg: TaggerConfig
) -> Signals:
    title, abstract, refs = lexical_matrices(art, corpus, dag, cfg)
    seed, desc = embedding_matrices(art, corpus, dag)
    source = source_matrix(art, corpus, dag, cfg.signals.openalex_min_score)
    venue = venue_matrix(art, corpus, dag, labels, cfg.signals.venue_smoothing)
    matrices = {
        "lex_title": title,
        "lex_abstract": abstract,
        "lex_refs": refs,
        "emb_seed": seed,
        "emb_desc": desc,
        "src_openalex": source,
        "venue_prior": venue,
    }
    assert set(matrices) == set(SIGNALS)
    return Signals(matrices, work_features(corpus.parts, corpus.emb_source))
