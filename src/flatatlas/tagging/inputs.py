"""Everything the tagger reads, loaded once: topics, the labelled set, text, vectors, sources.

Text comes only from ``flatatlas.text.composite`` (``build_parts``, via ``text.store.build_all``),
as P1-05 decided. Vectors are the Semantic Scholar SPECTER2 vectors where they exist and the local
SPECTER2 vectors otherwise (D-23).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np

from flatatlas.embed.store import normalise
from flatatlas.taxonomy import check as tcheck
from flatatlas.taxonomy.schema import GoldFile, TopicEntry, TopicsFile, topic_levels
from flatatlas.text import store as text_store
from flatatlas.text.composite import CompositeParts


@dataclass
class Dag:
    """The topic DAG with the derived structure the tagger needs."""

    topics: list[TopicEntry]
    ids: list[str]
    index: dict[str, int]
    level: np.ndarray  # shortest distance to a root
    parents: list[list[int]]
    children: list[list[int]]
    ancestors: list[list[int]]  # all, nearest first, not including the topic itself

    @classmethod
    def build(cls, file: TopicsFile) -> Dag:
        topics = [t for t in file.topics if t.status != "deprecated"]
        ids = [t.id for t in topics]
        index = {t: i for i, t in enumerate(ids)}
        levels = topic_levels(topics)
        parents = [[index[p] for p in t.parents if p in index] for t in topics]
        children: list[list[int]] = [[] for _ in topics]
        for i, ps in enumerate(parents):
            for p in ps:
                children[p].append(i)
        ancestors: list[list[int]] = []
        for i in range(len(topics)):
            seen: list[int] = []
            frontier = list(parents[i])
            while frontier:
                nxt: list[int] = []
                for a in frontier:
                    if a not in seen:
                        seen.append(a)
                        nxt.extend(parents[a])
                frontier = nxt
            ancestors.append(seen)
        return cls(
            topics=topics,
            ids=ids,
            index=index,
            level=np.array([levels.get(t, 0) for t in ids], dtype=np.int16),
            parents=parents,
            children=children,
            ancestors=ancestors,
        )

    @property
    def n(self) -> int:
        return len(self.ids)

    def descendants(self, i: int) -> list[int]:
        out: list[int] = []
        frontier = list(self.children[i])
        while frontier:
            nxt: list[int] = []
            for c in frontier:
                if c not in out:
                    out.append(c)
                    nxt.extend(self.children[c])
            frontier = nxt
        return out


@dataclass
class Corpus:
    """The works of the warehouse with their text parts, vectors and OpenAlex topics."""

    work_ids: list[str]
    index: dict[str, int]
    parts: list[CompositeParts]
    vectors: np.ndarray  # (n, 768) float32, unit length
    emb_source: np.ndarray  # 1 where the vector is from Semantic Scholar, 0 where local
    venues: list[str]
    openalex: list[dict[str, float]]  # per work: OpenAlex topic id -> best score
    n_in_corpus_refs: np.ndarray = field(default_factory=lambda: np.zeros(0))

    def __len__(self) -> int:
        return len(self.work_ids)


@dataclass
class Labels:
    """The labelled set arranged for the tagger."""

    gold: GoldFile
    by_work: dict[str, set[str]]  # work -> label topic ids
    split: dict[str, str]
    sampling: dict[str, str]

    @classmethod
    def build(cls, gold: GoldFile) -> Labels:
        return cls(
            gold=gold,
            by_work={w.work: set(w.labels) for w in gold.works},
            split={w.work: w.split for w in gold.works},
            sampling={w.work: w.sampling for w in gold.works},
        )

    def works(self, *, split: str | None = None, sampling: str | None = None) -> list[str]:
        return sorted(
            w
            for w in self.by_work
            if (split is None or self.split[w] == split)
            and (sampling is None or self.sampling[w] == sampling)
        )


def load_dag(path: Path = tcheck.TOPICS_FILE) -> tuple[TopicsFile, Dag]:
    file = tcheck.load_topics(path)
    return file, Dag.build(file)


def load_labels(path: Path = tcheck.GOLD_FILE) -> Labels:
    return Labels.build(tcheck.load_gold(path))


def openalex_topics(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, float]]:
    """``work_id -> {OpenAlex topic id: best score}`` over all versions of the work."""
    rows = con.execute(
        """
        SELECT v.work_id, t.topic_id, max(t.score)
        FROM core_version v
        JOIN stg_openalex_topic t ON t.openalex_id = v.openalex_id
        WHERE t.kind = 'topic' AND t.topic_id IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    ).fetchall()
    out: dict[str, dict[str, float]] = {}
    for work_id, topic_id, score in rows:
        out.setdefault(work_id, {})[topic_id] = float(score or 0.0)
    return out


def load_corpus(con: duckdb.DuckDBPyConnection) -> Corpus:
    """Load all works with the stored vectors (``local_embed`` may replace the local ones)."""
    parts = text_store.build_all(con)
    work_ids = [p.work_id for p in parts]
    index = {w: i for i, w in enumerate(work_ids)}
    rows = con.execute(
        "SELECT work_id, source, vector FROM local_work_embedding ORDER BY work_id"
    ).fetchall()
    vectors = np.zeros((len(work_ids), 768), dtype=np.float32)
    source = np.zeros(len(work_ids), dtype=np.int8)
    for work_id, src, vec in rows:
        i = index.get(work_id)
        if i is None:
            continue
        vectors[i] = np.asarray(vec, dtype=np.float32)
        source[i] = 1 if src == "s2" else 0
    oa = openalex_topics(con)
    return Corpus(
        work_ids=work_ids,
        index=index,
        parts=parts,
        vectors=normalise(vectors),
        emb_source=source,
        venues=[p.venue for p in parts],
        openalex=[oa.get(w, {}) for w in work_ids],
    )
