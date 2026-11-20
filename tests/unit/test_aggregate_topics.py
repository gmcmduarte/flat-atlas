"""Per-topic aggregates with hand-computed values (P1-09, D-102)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from flatatlas.aggregate import membership as mem
from flatatlas.aggregate import topics as T

TOPICS = ["t0", "t1"]


def toy():
    works = T.WorkTable(
        work_ids=["W0", "W1", "W2", "W3"],
        years=np.array([2000, 2000, 2001, 2001]),
        cited_by=np.array([3, 0, 10, 5]),
        venue_idx=np.array([0, 0, 1, 1]),
        venue_ids=["VA", "VB"],
        classes=[mem.TAGGED, mem.TAGGED, mem.LOW_CONFIDENCE, mem.UNTAGGED],
        authorship=(np.array([0, 2, 1, 3]), np.array([0, 0, 1, 1])),
        author_ids=["A0", "A1"],
    )
    m = np.array([[0.9, 0.0], [0.5, 0.4], [0.3, 0.0], [0.0, 0.0]])
    return works, m


def rows(table):
    return table.to_pylist()


def test_summary_separates_volume_from_counts():
    works, m = toy()
    s = T.summary(m, works, 0.35)
    assert s["volume"] == pytest.approx([0.9 + 0.5 + 0.3, 0.4])
    assert list(s["paper_count"]) == [2, 1]  # the low-confidence work is not counted
    assert list(s["n_low_confidence"]) == [1, 0]


def test_topic_year():
    works, m = toy()
    out = rows(T.topic_year(m, works, TOPICS, 0.35))
    t0 = {r["year"]: r for r in out if r["topic_id"] == "t0"}
    assert t0[2000]["papers"] == 2
    assert t0[2000]["volume"] == pytest.approx(1.4)
    assert t0[2000]["citations"] == 3  # 3 + 0
    assert t0[2001]["papers"] == 0 and t0[2001]["n_low_confidence"] == 1
    assert t0[2001]["volume"] == pytest.approx(0.3)
    assert [r["year"] for r in out if r["topic_id"] == "t1"] == [2000]


def test_topic_work_ranks_tagged_first_then_low_confidence():
    works, m = toy()
    out = [r for r in rows(T.topic_work(m, works, TOPICS)) if r["topic_id"] == "t0"]
    assert [r["work_id"] for r in out] == ["W0", "W1", "W2"]
    assert [r["rank"] for r in out] == [1, 2, 3]
    assert out[0]["score"] == pytest.approx(0.9 * math.log(4))
    assert out[1]["score"] == pytest.approx(0.0)  # no citations
    # the low-confidence work has the larger raw score (0.3 * ln 11) and still comes last
    assert out[2]["score"] == pytest.approx(0.3 * math.log(11))
    assert out[2]["low_confidence"] is True
    assert "W3" not in {r["work_id"] for r in rows(T.topic_work(m, works, TOPICS))}


def test_topic_author():
    works, m = toy()
    out = {(r["topic_id"], r["author_id"]): r for r in rows(T.topic_author(m, works, TOPICS, 0.35))}
    a0 = out[("t0", "A0")]  # works W0 (0.9, tagged) and W2 (0.3, low confidence)
    assert a0["score"] == pytest.approx(1.2)
    assert a0["n_works"] == 1
    assert (a0["first_year"], a0["last_year"]) == (2000, 2001)
    a1 = out[("t0", "A1")]  # W1 (0.5); W3 is untagged
    assert a1["score"] == pytest.approx(0.5) and a1["n_works"] == 1
    assert ("t1", "A0") not in out


def test_topic_venue():
    works, m = toy()
    out = {(r["topic_id"], r["venue_id"]): r for r in rows(T.topic_venue(m, works, TOPICS, 0.35))}
    va = out[("t0", "VA")]
    assert va["papers"] == 2 and va["volume"] == pytest.approx(1.4)
    vb = out[("t0", "VB")]
    assert vb["papers"] == 0 and vb["volume"] == pytest.approx(0.3)
    assert ("t1", "VB") not in out
