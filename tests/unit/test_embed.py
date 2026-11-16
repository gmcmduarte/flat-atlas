"""Embeddings (P1-03): input format, batching and resume, the one-vector rule, comparison.

No model is loaded or downloaded here: a fake encoder stands in for SPECTER2, so these run in the
base CI job, which does not install torch.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys

import numpy as np
import pyarrow as pa
import pytest

from flatatlas.abstracts import best_abstracts
from flatatlas.db import connect
from flatatlas.embed import specter2, stage, store

DIM = store.DIM


def fake_vector(text: str) -> np.ndarray:
    seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
    return np.random.default_rng(seed).normal(size=DIM).astype(np.float32)


class FakeEncoder:
    """Deterministic vectors from the text; remembers every batch it was asked for."""

    sep = "[SEP]"
    device = "cpu"

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.batches: list[list[str]] = []
        self.fail_on_call = fail_on_call

    def encode(self, texts):
        if self.fail_on_call is not None and len(self.batches) + 1 == self.fail_on_call:
            raise KeyboardInterrupt  # a killed job
        self.batches.append(list(texts))
        return np.vstack([fake_vector(t) for t in texts])


# -- input format --------------------------------------------------------------------------------


def test_input_is_title_sep_abstract_and_title_alone_without_an_abstract():
    assert specter2.format_input("A  title", "An\nabstract.", "[SEP]") == (
        "A title[SEP]An abstract.",
        "title+abstract",
    )
    assert specter2.format_input("A title", None) == ("A title", "title")
    assert specter2.format_input("A title", "  ") == ("A title", "title")


def test_the_model_card_variant_keeps_a_trailing_separator():
    assert specter2.format_input("A title", None, "[SEP]", sep_when_empty=True) == (
        "A title[SEP]",
        "title",
    )


def test_the_model_names_are_the_ones_on_the_model_card():
    assert specter2.BASE_MODEL == "allenai/specter2_base"
    assert specter2.ADAPTER == "allenai/specter2" and specter2.ADAPTER_NAME == "proximity"


def test_importing_the_embed_modules_does_not_import_torch():
    code = (
        "import sys; import flatatlas.embed.specter2, flatatlas.embed.stage, flatatlas.cli; "
        "print([m for m in ('torch', 'transformers', 'adapters') if m in sys.modules])"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


# -- batching and resume -------------------------------------------------------------------------


def test_vectors_come_back_in_input_order_in_batches_of_at_most_the_batch_size():
    texts = ["ccc", "a", "bb", "dddd", "eeeee"]
    enc = FakeEncoder()
    vectors, stats = specter2.embed_texts(texts, enc, batch_size=2)
    assert vectors.shape == (5, DIM)
    for text, vec in zip(texts, vectors, strict=True):
        assert np.allclose(vec, fake_vector(text))
    assert [len(b) for b in enc.batches] == [2, 2, 1] and stats.batches == 3
    assert stats.computed == 5 and stats.from_cache == 0
    assert enc.batches[0] == ["a", "bb"]  # shortest first: batches pad little


def test_equal_texts_are_computed_once():
    enc = FakeEncoder()
    vectors, stats = specter2.embed_texts(["x", "x", "y"], enc, batch_size=8)
    assert sum(len(b) for b in enc.batches) == 2 and stats.computed == 2
    assert np.allclose(vectors[0], vectors[1])


def test_empty_input_is_fine():
    vectors, stats = specter2.embed_texts([], FakeEncoder(), batch_size=4)
    assert vectors.shape == (0, DIM) and stats.batches == 0


def test_a_killed_run_resumes_from_the_finished_batches(tmp_path):
    cache = specter2.VectorCache(tmp_path / "cache")
    texts = [f"text {i:02d}" for i in range(7)]
    with pytest.raises(KeyboardInterrupt):
        specter2.embed_texts(texts, FakeEncoder(fail_on_call=3), batch_size=2, cache=cache)
    assert len(cache.load()) == 4  # two batches of two were saved before the kill

    enc = FakeEncoder()
    vectors, stats = specter2.embed_texts(texts, enc, batch_size=2, cache=cache)
    assert stats.from_cache == 4 and stats.computed == 3
    assert sum(len(b) for b in enc.batches) == 3
    assert np.allclose(vectors[5], fake_vector("text 05"))

    enc = FakeEncoder()
    _, stats = specter2.embed_texts(texts, enc, batch_size=2, cache=cache)
    assert enc.batches == [] and stats.computed == 0 and stats.from_cache == 7


def test_a_corrupt_cache_shard_is_ignored_and_recomputed(tmp_path):
    cache = specter2.VectorCache(tmp_path / "cache")
    specter2.embed_texts(["one", "two"], FakeEncoder(), batch_size=2, cache=cache)
    (shard,) = (tmp_path / "cache").glob("*.npz")
    shard.write_bytes(b"not a zip")
    enc = FakeEncoder()
    _, stats = specter2.embed_texts(["one", "two"], enc, batch_size=2, cache=cache)
    assert stats.computed == 2 and stats.from_cache == 0


def test_the_cache_is_keyed_by_model_and_text():
    assert specter2.text_hash("a") != specter2.text_hash("b")
    assert specter2.text_hash("a", "model-1") != specter2.text_hash("a", "model-2")


def test_an_encoder_returning_the_wrong_shape_is_an_error():
    class Bad:
        def encode(self, texts):
            return np.zeros((len(texts), 3), dtype=np.float32)

    with pytest.raises(RuntimeError, match="shape"):
        specter2.embed_texts(["a"], Bad(), batch_size=1)


# -- the vector table ----------------------------------------------------------------------------


def row(key: str, source: str, value: float = 0.1, **extra) -> dict:
    return {
        "dblp_key": key,
        "model": "m",
        "source": source,
        "s2_corpus_id": None,
        "input_kind": None,
        "abstract_source": None,
        "vector": [value] * DIM,
        **extra,
    }


@pytest.fixture
def con(settings):
    connection = connect(settings.paths)
    yield connection
    connection.close()


def test_one_row_per_paper_and_s2_beats_local(settings, con):
    store.write_source(con, settings.paths, "local", [row("a", "local"), row("b", "local")])
    n = store.write_source(con, settings.paths, "s2", [row("b", "s2", 0.9), row("c", "s2")])
    assert n == 3
    by_key = {r["dblp_key"]: r["source"] for r in store.read_rows(con)}
    assert by_key == {"a": "local", "b": "s2", "c": "s2"}
    # a local row written later for a paper that has an S2 vector does not displace it
    store.write_source(con, settings.paths, "local", [row("a", "local"), row("b", "local")])
    assert {r["dblp_key"]: r["source"] for r in store.read_rows(con)}["b"] == "s2"


def test_rewriting_a_source_replaces_its_rows_and_keeps_the_others(settings, con):
    store.write_source(con, settings.paths, "s2", [row("a", "s2"), row("b", "s2")])
    store.write_source(con, settings.paths, "local", [row("c", "local")])
    store.write_source(con, settings.paths, "s2", [row("a", "s2")])  # b is gone from the cache
    assert sorted((r["dblp_key"], r["source"]) for r in store.read_rows(con)) == [
        ("a", "s2"),
        ("c", "local"),
    ]


def test_rows_with_a_wrong_dimension_or_source_are_refused(settings, con):
    with pytest.raises(ValueError, match="768"):
        store.write_source(con, settings.paths, "s2", [row("a", "s2", vector=[0.0] * 3)])
    with pytest.raises(ValueError, match="source"):
        store.write_source(con, settings.paths, "s2", [row("a", "local")])
    with pytest.raises(ValueError, match="unknown"):
        store.write_source(con, settings.paths, "other", [])


def test_coverage_counts_missing_and_never_more_than_one(settings, con):
    store.write_source(con, settings.paths, "s2", [row("a", "s2")])
    store.write_source(con, settings.paths, "local", [row("b", "local"), row("a", "local")])
    cov = store.coverage(con, ["a", "b", "c"])
    assert cov == {
        "papers": 3,
        "with_vector": 2,
        "missing": 1,
        "duplicated": 0,
        "by_source": {"local": 1, "s2": 1},
    }


def test_cosine_topk_orders_by_similarity_and_can_skip_the_query_row():
    m = np.eye(4, DIM, dtype=np.float32)
    m[3] = m[0] + 0.1 * m[1]
    top = store.cosine_topk(m, m[0], k=3)
    assert [i for i, _ in top][:2] == [0, 3] and top[0][1] == pytest.approx(1.0)
    assert [i for i, _ in store.cosine_topk(m, m[0], k=2, exclude=0)] == [3, 1]
    assert store.cosine_topk(np.zeros((0, DIM), dtype=np.float32), m[0]) == []
    assert len(store.cosine_topk(m, m[0], k=50)) == 4


def test_cosine_pairs_ignore_length():
    a = np.vstack([fake_vector("x"), fake_vector("y")])
    assert store.cosine_pairs(a, a * 7) == pytest.approx([1.0, 1.0])
    assert store.cosine_pairs(a[:1], -a[:1]) == pytest.approx([-1.0])


# -- abstracts: which one a paper uses -----------------------------------------------------------


def put_abstracts(con, rows: list[tuple[str, str, str]]) -> None:
    table = pa.Table.from_pylist(
        [
            {"dblp_key": k, "openalex_id": None, "doi": None, "source": s, "text": t, "n_chars": 1}
            for k, s, t in rows
        ]
    )
    con.register("_a", table)
    con.execute("CREATE OR REPLACE TABLE local_abstract AS SELECT * FROM _a")
    con.unregister("_a")


def test_abstract_priority_is_openalex_then_s2_then_crossref(con):
    assert best_abstracts(con) == {}  # no table yet
    put_abstracts(
        con,
        [
            ("p1", "crossref", "cr"),
            ("p1", "s2", "s2"),
            ("p1", "openalex", "oa"),
            ("p2", "crossref", "cr"),
            ("p2", "s2", "s2"),
            ("p3", "crossref", "cr"),
            ("p4", "s2", ""),  # empty text is not an abstract
        ],
    )
    assert best_abstracts(con) == {
        "p1": ("openalex", "oa"),
        "p2": ("s2", "s2"),
        "p3": ("crossref", "cr"),
    }


# -- the stage -----------------------------------------------------------------------------------


def put_papers(con, rows: list[tuple[str, str, str | None, bool]]) -> None:
    table = pa.Table.from_pylist(
        [
            {"dblp_key": k, "venue_id": "dlt", "title": t, "is_front_matter": fm}
            for k, t, _d, fm in rows
        ]
    )
    con.register("_p", table)
    con.execute("CREATE OR REPLACE TABLE stg_dblp_paper AS SELECT * FROM _p")
    con.unregister("_p")


@pytest.fixture
def pilot(settings, con):
    put_papers(
        con,
        [
            ("k/a", "Alpha automata", None, False),  # has an S2 vector
            ("k/b", "Beta grammars", None, False),  # no vector anywhere: local, with abstract
            ("k/c", "Gamma languages", None, False),  # local, title only
            ("k/d", "Delta transducers", None, False),  # local, title only
            ("k/front", "Preface", None, True),
        ],
    )
    put_abstracts(con, [("k/b", "crossref", "A short abstract about grammars.")])
    store.write_source(con, settings.paths, "s2", [row("k/a", "s2", 0.7)])
    return stage.load_paper_texts(con)


def test_load_paper_texts_skips_front_matter_and_attaches_the_best_abstract(pilot):
    assert [p.dblp_key for p in pilot] == ["k/a", "k/b", "k/c", "k/d"]
    by_key = {p.dblp_key: p for p in pilot}
    assert by_key["k/b"].abstract and by_key["k/b"].abstract_source == "crossref"
    assert by_key["k/c"].abstract is None


def test_embed_gives_the_papers_without_an_s2_vector_a_local_one(settings, con, pilot):
    enc = FakeEncoder()
    result = stage.run_embed(con, settings.paths, enc, pilot, batch_size=2)
    assert result.wanted == 3 and result.done == 3
    assert result.kinds == {"title+abstract": 1, "title": 2}
    rows = {r["dblp_key"]: r for r in store.read_rows(con)}
    assert {k: r["source"] for k, r in rows.items()} == {
        "k/a": "s2",
        "k/b": "local",
        "k/c": "local",
        "k/d": "local",
    }
    assert (
        rows["k/b"]["input_kind"] == "title+abstract"
        and rows["k/b"]["abstract_source"] == "crossref"
    )
    assert rows["k/c"]["input_kind"] == "title" and rows["k/c"]["abstract_source"] is None
    assert rows["k/a"]["vector"][0] == pytest.approx(0.7)  # the S2 row is untouched
    sent = [t for b in enc.batches for t in b]
    assert "Beta grammars[SEP]A short abstract about grammars." in sent
    assert "Gamma languages" in sent and "Alpha automata" not in sent
    assert result.coverage["missing"] == 0 and result.coverage["duplicated"] == 0


def test_a_limit_run_adds_to_earlier_local_rows_and_a_rerun_computes_nothing(settings, con, pilot):
    first = stage.run_embed(con, settings.paths, FakeEncoder(), pilot, limit=1, batch_size=8)
    assert first.done == 1 and first.coverage["missing"] == 2
    second = stage.run_embed(con, settings.paths, FakeEncoder(), pilot, batch_size=8)
    assert second.done == 3 and second.coverage["missing"] == 0
    assert second.stats.from_cache == 1 and second.stats.computed == 2  # the first one is cached
    third_enc = FakeEncoder()
    third = stage.run_embed(con, settings.paths, third_enc, pilot, batch_size=8)
    assert third_enc.batches == [] and third.coverage["with_vector"] == 4


def test_the_sample_of_a_limit_run_is_stable():
    keys = [f"k/{i}" for i in range(20)]
    first = sorted(keys, key=stage.sample_order)[:5]
    assert first == sorted(reversed(keys), key=stage.sample_order)[:5]


def test_an_s2_vector_that_arrives_later_replaces_the_local_one(settings, con, pilot):
    stage.run_embed(con, settings.paths, FakeEncoder(), pilot, batch_size=8)
    store.write_source(con, settings.paths, "s2", [row("k/a", "s2", 0.7), row("k/c", "s2", 0.3)])
    rows = {r["dblp_key"]: r["source"] for r in store.read_rows(con)}
    assert rows["k/c"] == "s2" and store.coverage(con, list(rows))["duplicated"] == 0
    assert stage.papers_without_s2_vector(con, pilot)[0].dblp_key == "k/b"


def test_compare_embeds_papers_that_have_an_s2_vector_and_reports_cosine(settings, con, pilot):
    # Give the S2 side the very vectors the fake model would produce, so the cosine is 1.
    enc = FakeEncoder()
    rows = []
    for p in pilot[:3]:
        text, _kind = specter2.format_input(p.title, p.abstract, enc.sep)
        rows.append(row(p.dblp_key, "s2", vector=fake_vector(text).tolist()))
    store.write_source(con, settings.paths, "s2", rows)
    comparison = stage.compare_with_s2(con, enc, pilot, n=10, batch_size=4)
    assert comparison.n == 3
    summary = stage.summarise(comparison)
    assert summary["all"]["mean"] == pytest.approx(1.0, abs=1e-5)
    assert summary["title+abstract"]["n"] == 1 and summary["title"]["n"] == 2
    # the model-card variant (trailing separator) was embedded too for the title-only papers
    assert summary["title (with trailing [SEP], model-card style)"]["n"] == 2
    text = stage.render_comparison(comparison, profile="test")
    assert "mean cosine" in text and "Lowest five" in text and "texts/s" in text
