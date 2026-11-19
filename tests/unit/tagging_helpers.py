"""Tiny synthetic topics, works and vectors for the tagger tests (no warehouse needed)."""

from __future__ import annotations

import numpy as np

from flatatlas.embed.store import normalise
from flatatlas.tagging.config import TaggerConfig, load_config
from flatatlas.tagging.descriptions import DescSpace
from flatatlas.tagging.inputs import Corpus, Dag, Labels
from flatatlas.taxonomy.schema import GoldFile, TopicsFile
from flatatlas.text.composite import CompositeParts

DIM = 16


def cfg() -> TaggerConfig:
    return load_config()


def topics_file() -> TopicsFile:
    def topic(id_, parents=(), include=(), exclude=(), aliases=(), name=None, openalex=()):
        return {
            "id": id_,
            "name": name or id_.replace("-", " "),
            "aliases": list(aliases),
            "description": f"About {id_}.",
            "parents": list(parents),
            "xref": {"openalex": list(openalex)},
            "include_phrases": list(include),
            "exclude_phrases": list(exclude),
            "seed_works": [],
            "origin": "manual",
            "reviewed": True,
        }

    return TopicsFile.model_validate(
        {
            "taxonomy_version": 1,
            "topics": [
                topic(
                    "regular-languages",
                    include=[
                        "finite automata",
                        "regular languages",
                        {"phrase": "minimal", "context": ["automaton", "automata"]},
                    ],
                    exclude=["pushdown"],
                    openalex=["T1"],
                ),
                topic(
                    "deterministic-finite-automata",
                    parents=["regular-languages"],
                    include=["deterministic finite automata"],
                    aliases=["dfa"],
                ),
                topic(
                    "combinatorics-on-words",
                    include=["combinatorics on words", "square-free words"],
                ),
                topic("avoidability", parents=["combinatorics-on-words"], include=["avoidable"]),
            ],
        }
    )


def part(work_id, title, *, refs=(), abstract="", tldr="", venue="DLT", year="2010"):
    return CompositeParts(
        work_id=work_id,
        title=title,
        venue=venue,
        year=year,
        reference_titles=tuple(refs),
        abstract=abstract,
        tldr=tldr,
        n_references=len(refs),
        n_references_with_title=len(refs),
        abstract_source="x" if abstract else None,
    )


def corpus_of(parts, *, seed=0, openalex=None) -> Corpus:
    rng = np.random.default_rng(seed)
    vectors = normalise(rng.normal(size=(len(parts), DIM)).astype(np.float32))
    ids = [p.work_id for p in parts]
    return Corpus(
        work_ids=ids,
        index={w: i for i, w in enumerate(ids)},
        parts=list(parts),
        vectors=vectors,
        emb_source=np.ones(len(ids), dtype=np.int8),
        venues=[p.venue for p in parts],
        openalex=openalex or [{} for _ in ids],
    )


def labels_of(entries) -> Labels:
    """``entries``: (work, labels, split, sampling)."""
    return Labels.build(
        GoldFile.model_validate(
            {
                "taxonomy_version": 1,
                "works": [
                    {
                        "work": w,
                        "labels": list(labs),
                        "split": split,
                        "sampling": sampling,
                        "reviewed": True,
                    }
                    for w, labs, split, sampling in entries
                ],
            }
        )
    )


def desc_space(n_topics: int, seed=1) -> DescSpace:
    rng = np.random.default_rng(seed)
    return DescSpace("specter2", normalise(rng.normal(size=(n_topics, DIM)).astype(np.float32)))


def dag_of(file: TopicsFile) -> Dag:
    return Dag.build(file)


def build(parts, labels_entries, *, topic_seed=0):
    """Topics, corpus, labels and artefacts for a list of parts."""
    from flatatlas.tagging import artefacts as art_mod

    file = topics_file()
    dag = dag_of(file)
    corpus = corpus_of(parts, seed=topic_seed)
    labels = labels_of(labels_entries)
    art = art_mod.build_artefacts(
        file, dag, corpus, labels, cfg(), [], desc_space(dag.n), key="test"
    )
    return file, dag, corpus, labels, art


def small_parts():
    titles = [
        "Deterministic finite automata revisited",
        "Deterministic finite automata and subset construction",
        "Finite automata minimisation",
        "Regular languages of words",
        "Square-free words and avoidable patterns",
        "Combinatorics on words today",
        "Avoidable patterns in words",
        "A survey of cities",
        "Pushdown automata and grammars",
        "Another paper on regular languages",
        "Unrelated topic one",
        "Unrelated topic two",
    ]
    return [part(f"W{i:010d}", t, venue="DLT" if i % 2 else "WORDS") for i, t in enumerate(titles)]
