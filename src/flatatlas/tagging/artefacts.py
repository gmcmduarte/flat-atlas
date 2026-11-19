"""Per-topic artefacts (PLAN §9.2): built once, cached, frozen per ``tagger_version``.

For each topic: a weighted phrase dictionary (include phrases, aliases, the name, mined reordering
variants, close phrase neighbours), exclude phrases, a seed set, 1 to 3 centroids of the seed
vectors, the description embedding, the mapped OpenAlex topics, the topic context features and the
score distributions the embedding signals are turned into percentiles against.

**Held-out works never enter** a seed set, a centroid or a score distribution (D-61): seeds go
through ``Guard.drop`` (``topics.yaml`` is human-edited and may name one; it is not edited here,
the drops are reported) and the reference distributions use only random-sample or unlabelled
works. Top-up works are not a random sample, so they are left out of the distributions too.

A seed work scored against its own topic would see itself in the centroid, so every centroid score
of a seed member is computed **without that member** (leave one out). The distributions use the same
rule, so a work's percentile means the same thing whether or not it is a seed.
"""

from __future__ import annotations

import hashlib
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from flatatlas.tagging.config import TaggerConfig, artefact_hash
from flatatlas.tagging.descriptions import DescSpace
from flatatlas.tagging.guard import Guard
from flatatlas.tagging.inputs import Corpus, Dag, Labels
from flatatlas.tagging.matcher import Matcher, PhraseEntry, tokenise
from flatatlas.taxonomy.phrases import key_of
from flatatlas.taxonomy.schema import TopicsFile, phrase_text

SEED_KINDS = frozenset({"include", "alias", "name"})


# -- phrase dictionary -------------------------------------------------------------------------


def build_dictionary(
    topics_file: TopicsFile, dag: Dag, cfg: TaggerConfig, mined: list[dict]
) -> tuple[Matcher, Matcher]:
    """The include and the exclude matcher."""
    p = cfg.phrases
    by_key = {r["key"]: r for r in mined}
    include: list[PhraseEntry] = []
    exclude: list[PhraseEntry] = []
    for topic in topics_file.topics:
        i = dag.index.get(topic.id)
        if i is None:
            continue

        def add(
            text,
            weight,
            kind,
            context=(),
            _i=i,
        ):
            toks = tuple(tokenise(text))
            if not toks:
                return
            if len(toks) == 1:
                weight *= p.single_token_factor
            include.append(
                PhraseEntry(_i, toks, weight, frozenset(tokenise(" ".join(context))), kind)
            )

        for phrase in topic.include_phrases:
            ctx = () if isinstance(phrase, str) else tuple(phrase.context)
            text = phrase_text(phrase)
            add(text, p.weight_include, "include", ctx)
            row = by_key.get(key_of(text))
            if row is None:
                continue
            base = tuple(tokenise(text))
            for variant in row["variants"]:
                vt = tuple(tokenise(variant))
                if vt != base and sorted(vt) == sorted(base):  # same words, other order
                    add(variant, p.weight_variant, "variant", ctx)
            for neighbour in row["merge_suggestions"]:
                nt = tokenise(neighbour["phrase"])
                if (
                    neighbour["cosine"] >= p.neighbour_min_cosine
                    and len(nt) >= p.neighbour_min_tokens
                ):
                    add(neighbour["phrase"], p.weight_neighbour, "neighbour", ctx)
        for alias in topic.aliases:
            add(alias, p.weight_alias, "alias")
        add(topic.name, p.weight_name, "name")
        for phrase in topic.exclude_phrases:
            toks = tuple(tokenise(phrase_text(phrase)))
            if toks:
                exclude.append(PhraseEntry(i, toks, 1.0, frozenset(), "exclude"))
    return Matcher(include), Matcher(exclude)


# -- k-means and centroids ---------------------------------------------------------------------


def kmeans(x: np.ndarray, k: int, iterations: int) -> np.ndarray:
    """Cluster labels of unit vectors ``x`` (cosine k-means, deterministic farthest-first start)."""
    n = len(x)
    if k <= 1 or n <= k:
        return np.zeros(n, dtype=np.int64)
    mean = x.mean(axis=0)
    first = int(np.argmax(x @ mean))
    chosen = [first]
    while len(chosen) < k:
        sim = np.max(x @ x[chosen].T, axis=1)
        sim[chosen] = np.inf
        chosen.append(int(np.argmin(sim)))
    centers = x[chosen].copy()
    labels = np.argmax(x @ centers.T, axis=1)
    for _ in range(iterations):
        new_centers = centers.copy()
        for c in range(k):
            members = x[labels == c]
            if len(members):
                v = members.sum(axis=0)
                new_centers[c] = v / max(np.linalg.norm(v), 1e-12)
        new_labels = np.argmax(x @ new_centers.T, axis=1)
        centers = new_centers
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
    return labels


@dataclass
class Centroids:
    """The centroids of one topic: sums of unit vectors (so a member can be left out)."""

    sums: np.ndarray  # (k, d)
    counts: np.ndarray  # (k,)
    members: dict[int, int]  # corpus index -> centroid number
    spread: float  # mean cosine distance of the seeds to their (single) centroid

    def scores(self, x: np.ndarray, rows: np.ndarray | None = None) -> np.ndarray:
        """Best cosine to a centroid for every row of ``x``; ``rows`` are the corpus indexes.

        A row that is a seed member is scored against its centroid without itself.
        """
        norms = np.maximum(np.linalg.norm(self.sums, axis=1, keepdims=True), 1e-12)
        out = np.max(x @ (self.sums / norms).T, axis=1)
        if rows is not None and self.members:
            hit = np.flatnonzero(np.isin(rows, np.fromiter(self.members, dtype=np.int64)))
            for pos in hit:
                c = self.members[int(rows[pos])]
                if self.counts[c] < 2:
                    continue
                sums = self.sums.copy()
                sums[c] = sums[c] - x[pos]
                norm = np.maximum(np.linalg.norm(sums, axis=1), 1e-12)
                out[pos] = float(np.max((sums @ x[pos]) / norm))
        return out


def build_centroids(
    seed_rows: list[int], vectors: np.ndarray, cfg: TaggerConfig
) -> Centroids | None:
    if len(seed_rows) < 2:
        return None
    e = cfg.embedding
    x = vectors[seed_rows]
    mean = x.mean(axis=0)
    mean = mean / max(np.linalg.norm(mean), 1e-12)
    spread = float(np.mean(1.0 - x @ mean))
    k = 1
    if spread > e.centroid_spread_split:
        k = max(1, min(e.max_centroids, len(seed_rows) // e.min_seeds_per_centroid))
    labels = kmeans(x, k, e.kmeans_iterations)
    sums = np.vstack([x[labels == c].sum(axis=0) for c in range(k)])
    counts = np.array([(labels == c).sum() for c in range(k)])
    keep = counts > 0
    remap = {int(old): new for new, old in enumerate(np.flatnonzero(keep))}
    members = {seed_rows[j]: remap[int(labels[j])] for j in range(len(seed_rows))}
    return Centroids(sums[keep], counts[keep], members, spread)


# -- the artefact bundle -----------------------------------------------------------------------


@dataclass
class Artefacts:
    tagger_version: str
    taxonomy_version: int
    key: str
    include: Matcher
    exclude: Matcher
    seeds: list[list[int]]  # per topic: corpus rows
    seeds_dropped: dict[str, list[str]]  # topic id -> held-out works removed from seed_works
    centroids: list[Centroids | None]
    desc_model: str
    desc_topic: np.ndarray  # (topics, d)
    desc_work: np.ndarray | None  # (works, d) when the model is not the corpus one
    ref_seed: list[np.ndarray]  # sorted reference cosines per topic (emb_seed)
    ref_desc: list[np.ndarray]  # sorted reference cosines per topic (emb_desc)
    oa_topics: list[frozenset[str]]  # mapped OpenAlex topic ids per topic
    topic_features: dict[str, np.ndarray]  # level, n_children, seed_size, seed_spread, n_phrases
    venue_counts: dict[str, np.ndarray]  # venue -> labels per topic (random training works)
    venue_n: dict[str, int]
    base_rate: np.ndarray | None = None  # share of random training works labelled with the topic
    reference_rows: np.ndarray | None = None  # corpus rows the distributions come from

    def save(self, path: Path) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = pickle.dumps(self, protocol=pickle.HIGHEST_PROTOCOL)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(path)
        return hashlib.sha256(blob).hexdigest()

    @staticmethod
    def load(path: Path) -> Artefacts:
        return pickle.loads(path.read_bytes())  # noqa: S301 - a file this program wrote


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "none"


def cache_key(
    cfg: TaggerConfig, taxonomy_version: int, topics_path: Path, gold_path: Path, corpus: Corpus
) -> str:
    fingerprint = hashlib.sha256("\n".join(corpus.work_ids).encode()).hexdigest()[:10]
    parts = [
        cfg.tagger_version,
        f"tax{taxonomy_version}",
        file_sha(topics_path)[:10],
        file_sha(gold_path)[:10],
        artefact_hash(cfg),
        fingerprint,
    ]
    return "-".join(parts)


def title_seeds(
    matcher: Matcher, exclude: Matcher, dag: Dag, corpus: Corpus, guard: Guard, limit: int
) -> list[list[int]]:
    """Per topic, works whose title holds one of its own phrases (the highest-precision matches).

    Longer phrases first (a one-word match is weak), ties by a hash of the work ID. Held-out works
    and works whose title holds an exclude phrase of the topic are never seeds.
    """
    scored: list[dict[int, int]] = [dict() for _ in range(dag.n)]
    for row, part in enumerate(corpus.parts):
        if part.work_id in guard.heldout:
            continue
        toks = tokenise(part.title)
        hits = [m for m in matcher.find(toks, frozenset(toks)) if m.entry.kind in SEED_KINDS]
        if not hits:
            continue
        vetoed = {m.entry.topic for m in exclude.find(toks)}
        for m in hits:
            t = m.entry.topic
            if t in vetoed:
                continue
            n = m.end - m.start
            if n > scored[t].get(row, 0):
                scored[t][row] = n
    out: list[list[int]] = []
    for t in range(dag.n):
        ranked = sorted(
            scored[t],
            key=lambda r: (
                -scored[t][r],
                hashlib.sha256(corpus.work_ids[r].encode()).hexdigest(),
            ),
        )
        out.append(ranked[:limit])
    return out


def build_artefacts(
    topics_file: TopicsFile,
    dag: Dag,
    corpus: Corpus,
    labels: Labels,
    cfg: TaggerConfig,
    mined: list[dict],
    desc: DescSpace,
    *,
    key: str,
) -> Artefacts:
    guard = Guard(labels.gold)
    include, exclude = build_dictionary(topics_file, dag, cfg, mined)
    by_title = title_seeds(include, exclude, dag, corpus, guard, cfg.phrases.max_title_seeds)

    seeds: list[list[int]] = []
    dropped: dict[str, list[str]] = {}
    for i, topic in enumerate(dag.topics):
        kept, gone = guard.drop(topic.seed_works)
        if gone:
            dropped[topic.id] = sorted(gone)
        rows = {corpus.index[w] for w in kept if w in corpus.index}
        rows.update(by_title[i])
        seeds.append(sorted(rows))
    centroids = [build_centroids(rows, corpus.vectors, cfg) for rows in seeds]

    # The reference works: random-sample or unlabelled works, never held-out, never top-up.
    reference = np.array(
        [
            r
            for r, w in enumerate(corpus.work_ids)
            if w not in guard.heldout and labels.sampling.get(w) != "topup"
        ],
        dtype=np.int64,
    )
    ref_vectors = corpus.vectors[reference]
    desc_work = desc.work_vectors if desc.work_vectors is not None else corpus.vectors
    ref_seed: list[np.ndarray] = []
    ref_desc: list[np.ndarray] = []
    for i in range(dag.n):
        c = centroids[i]
        ref_seed.append(
            np.sort(c.scores(ref_vectors, reference)) if c is not None else np.zeros(0, np.float32)
        )
        ref_desc.append(np.sort(desc_work[reference] @ desc.topic_vectors[i]))

    train_random = [w for w in labels.works(split="train", sampling="random") if w in corpus.index]
    guard.check(train_random, purpose="venue priors")
    venue_counts: dict[str, np.ndarray] = {}
    venue_n: dict[str, int] = {}
    base = np.zeros(dag.n)
    for w in train_random:
        v = corpus.venues[corpus.index[w]]
        vec = venue_counts.setdefault(v, np.zeros(dag.n))
        venue_n[v] = venue_n.get(v, 0) + 1
        for label in labels.by_work[w]:
            if label in dag.index:
                vec[dag.index[label]] += 1
                base[dag.index[label]] += 1
    base = base / max(len(train_random), 1)

    n_phrases = np.zeros(dag.n)
    for e in include.entries:
        n_phrases[e.topic] += 1
    topic_features = {
        "t_level": dag.level.astype(np.float32),
        "t_n_children": np.array([len(c) for c in dag.children], dtype=np.float32),
        "t_seed_size": np.array([len(s) for s in seeds], dtype=np.float32),
        "t_seed_spread": np.array(
            [c.spread if c is not None else np.nan for c in centroids], dtype=np.float32
        ),
        "t_n_phrases": n_phrases.astype(np.float32),
    }
    return Artefacts(
        tagger_version=cfg.tagger_version,
        taxonomy_version=topics_file.taxonomy_version,
        key=key,
        include=include,
        exclude=exclude,
        seeds=seeds,
        seeds_dropped=dropped,
        centroids=centroids,
        desc_model=desc.model,
        desc_topic=desc.topic_vectors,
        desc_work=desc.work_vectors,
        ref_seed=ref_seed,
        ref_desc=ref_desc,
        oa_topics=[frozenset(t.xref.openalex) for t in dag.topics],
        topic_features=topic_features,
        venue_counts=venue_counts,
        venue_n=venue_n,
        base_rate=base,
        reference_rows=reference,
    )
