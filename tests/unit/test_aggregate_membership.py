"""Roll-up of tags to topics, with hand-computed values (P1-09, D-102)."""

from __future__ import annotations

import numpy as np
import pytest

from flatatlas.aggregate import membership as mem

# A diamond: g above p1 and p2, both above c; o stands alone.
DIAMOND = mem.TopicGraph.from_parents(
    {"g": [], "p1": ["g"], "p2": ["g"], "c": ["p1", "p2"], "o": []}
)


def test_the_graph_knows_ancestors_descendants_and_levels():
    g = DIAMOND
    idx = g.index
    assert g.ancestors[idx["c"]] == frozenset({idx["p1"], idx["p2"], idx["g"]})
    assert g.descendants[idx["g"]] == frozenset({idx["p1"], idx["p2"], idx["c"]})
    assert g.levels == [0, 1, 1, 2, 0]


def test_related_mask_covers_self_and_ancestors_only():
    mask = DIAMOND.related_mask()
    idx = DIAMOND.index
    assert mask[idx["c"], idx["g"]] and mask[idx["g"], idx["c"]]
    assert mask[idx["o"], idx["o"]]
    assert not mask[idx["p1"], idx["p2"]]  # siblings are not ancestors of each other
    assert not mask[idx["c"], idx["o"]]


def test_base_matrix_skips_derived_rows_and_keeps_the_larger_repeat():
    work_index = {"W1": 0, "W2": 1}
    topic_index = DIAMOND.index
    tags = [
        ("W1", "c", 0.8, False),
        ("W1", "p1", 0.9, True),  # derived: ignored
        ("W2", "p1", 0.4, False),
        ("W2", "p1", 0.6, False),  # a repeat: the larger wins
        ("W9", "c", 0.5, False),  # unknown work: ignored
    ]
    base = mem.base_matrix(work_index, topic_index, tags)
    assert base[0, topic_index["c"]] == pytest.approx(0.8)
    assert base[0, topic_index["p1"]] == 0
    assert base[1, topic_index["p1"]] == pytest.approx(0.6)


def test_roll_up_counts_a_work_once_inside_an_ancestor():
    idx = DIAMOND.index
    base = np.zeros((3, 5), dtype=np.float32)
    base[0, idx["c"]] = 0.8  # one tag at the bottom of the diamond
    base[1, idx["p1"]] = 0.6  # two tags under one parent
    base[1, idx["p2"]] = 0.5
    base[2, idx["c"]] = 0.4  # a tag and a better tag of its ancestor
    base[2, idx["p1"]] = 0.9
    m = mem.roll_up(base, DIAMOND)

    # work 0: c = 0.8 reaches p1, p2 and g once each (the sum would be 1.6 if both paths counted)
    assert [m[0, idx[t]] for t in ("c", "p1", "p2", "g", "o")] == pytest.approx(
        [0.8, 0.8, 0.8, 0.8, 0.0]
    )
    # work 1: g takes the larger of 0.6 and 0.5, not 1.1
    assert m[1, idx["g"]] == pytest.approx(0.6)
    assert m[1, idx["c"]] == 0
    # work 2: p1 keeps its own 0.9; p2 only has c's 0.4
    assert m[2, idx["p1"]] == pytest.approx(0.9)
    assert m[2, idx["p2"]] == pytest.approx(0.4)
    assert m[2, idx["g"]] == pytest.approx(0.9)
    # the volume of g is 0.8 + 0.6 + 0.9
    assert m[:, idx["g"]].sum() == pytest.approx(2.3)


def test_work_classes():
    classes = mem.work_classes(
        ["W1", "W2", "W3"],
        {"W2": {"low_confidence"}},
        {"W1", "W2"},
    )
    assert classes == [mem.TAGGED, mem.LOW_CONFIDENCE, mem.UNTAGGED]
