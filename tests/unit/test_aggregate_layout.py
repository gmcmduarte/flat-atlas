"""Map layout: packing, primary parents, determinism, no overlap (P1-09, D-102)."""

from __future__ import annotations

import math
import random

import numpy as np
import pytest

from flatatlas.aggregate import layout as L
from flatatlas.aggregate import membership as mem
from flatatlas.aggregate.config import LayoutConfig

# Two roots; r1 has c1 and c2, c1 has d; c2 also sits under r2 (a second parent).
GRAPH = mem.TopicGraph.from_parents(
    {"r1": [], "r2": [], "c1": ["r1"], "c2": ["r1", "r2"], "d": ["c1"], "e": ["r2"]}
)


def test_pack_two_circles_touch():
    centres, enclose = L.pack_circles([1.0, 1.0], pad=0.0)
    assert math.dist(centres[0], centres[1]) == pytest.approx(2.0)
    assert enclose == pytest.approx(2.0)


def test_pack_one_circle():
    centres, enclose = L.pack_circles([3.0], pad=0.5)
    assert centres == [(0.0, 0.0)] and enclose == pytest.approx(3.0)


def test_pack_never_overlaps_and_is_deterministic():
    rng = random.Random(4)
    radii = [rng.uniform(0.3, 3.0) for _ in range(25)]
    centres, enclose = L.pack_circles(radii, pad=0.1)
    for i in range(len(radii)):
        assert math.hypot(*centres[i]) + radii[i] <= enclose + 1e-9
        for j in range(i + 1, len(radii)):
            assert math.dist(centres[i], centres[j]) >= radii[i] + radii[j] + 0.1 - 1e-6
    assert L.pack_circles(radii, pad=0.1) == (centres, enclose)


def test_separate_resolves_overlaps():
    pos = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 0.5]])
    radii = np.array([2.0, 2.0, 2.0])
    out = L.separate(pos, radii, gap=0.5)
    for i in range(3):
        for j in range(i + 1, 3):
            assert np.hypot(*(out[i] - out[j])) >= 4.5 - 1e-6


def test_primary_parent_follows_shared_evidence():
    idx = GRAPH.index
    base = np.zeros((4, GRAPH.n), dtype=np.float32)
    for w in range(3):  # three works tagged c2 (0.9) and r2 itself (0.8)
        base[w, idx["c2"]] = 0.9
        base[w, idx["r2"]] = 0.8
    base[3, idx["c2"]] = 0.9  # one work tagged c2 and c1 (0.7), which is under r1
    base[3, idx["c1"]] = 0.7
    m = mem.roll_up(base, GRAPH)
    volume = m.sum(axis=0)
    primary = L.primary_parents(GRAPH, base, m, volume)
    # r2: min(0.9, 0.8) on three works = 2.4; r1: the evidence outside c2 is c1's 0.7 on one work
    assert primary[idx["c2"]] == idx["r2"]
    assert primary[idx["c1"]] == idx["r1"]  # a single parent
    assert idx["r1"] not in primary  # roots have none


def test_primary_parent_tie_goes_to_the_larger_then_the_smaller_id():
    graph = mem.TopicGraph.from_parents({"a": [], "b": [], "c": ["a", "b"]})
    base = np.zeros((1, 3), dtype=np.float32)
    m = base.copy()
    volume = np.array([1.0, 1.0, 0.0])
    assert L.primary_parents(graph, base, m, volume) == {2: 0}  # equal volumes: id "a"
    volume = np.array([1.0, 2.0, 0.0])
    assert L.primary_parents(graph, base, m, volume) == {2: 1}  # the larger parent


def _layout(volume=None):
    idx = GRAPH.index
    volume = np.array([10.0, 6.0, 4.0, 3.0, 1.0, 2.0]) if volume is None else volume
    primary = {idx["c1"]: idx["r1"], idx["c2"]: idx["r2"], idx["d"]: idx["c1"], idx["e"]: idx["r2"]}
    lateral = [(idx["c1"], idx["e"], 0.5)]
    cfg = LayoutConfig()
    nodes = L.compute_layout(GRAPH, volume, primary, lateral, cfg)
    return nodes, volume, cfg


def test_layout_has_no_overlapping_siblings_and_children_stay_inside():
    nodes, *_ = _layout()
    by = {n.topic: n for n in nodes}
    for a in nodes:
        for b in nodes:
            if a.topic < b.topic and a.parent == b.parent:
                assert math.hypot(a.x - b.x, a.y - b.y) >= a.r + b.r - 1e-6
        if a.parent is not None:
            p = by[a.parent]
            assert math.hypot(a.x - p.x, a.y - p.y) + a.r <= p.r + 1e-6


def test_layout_is_deterministic_and_records_ghost_parents():
    nodes1, volume, cfg = _layout()
    nodes2, *_ = _layout()
    t1 = L.layout_table(GRAPH, nodes1, volume, cfg.decimals)
    t2 = L.layout_table(GRAPH, nodes2, volume, cfg.decimals)
    assert t1.equals(t2)
    out = {r["topic_id"]: r for r in t1.to_pylist()}
    assert out["c2"]["parent_id"] == "r2" and out["c2"]["ghost_parents"] == ["r1"]
    assert out["r1"]["parent_id"] is None and out["r1"]["level"] == 0
    assert out["d"]["level"] == 2 and out["d"]["year"] is None


def test_largest_root_has_the_root_radius():
    nodes, *_ = _layout()
    roots = [n for n in nodes if n.parent is None]
    assert max(n.r for n in roots) == pytest.approx(LayoutConfig().root_radius)
