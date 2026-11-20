"""The precomputed topic map (PLAN §11.4, D-102): one disc per topic, all-time, deterministic.

* Level-0 topics (roots) sit where a ForceAtlas2-style force layout puts them: the three lateral
  edge types, aggregated from each topic's descendants to its root, are the springs. The forces
  are FA2's (degree-weighted repulsion, linear attraction, constant gravity, overlap prevention);
  the speed control is a simple linear cooling instead of FA2's adaptive swing rule, and a last
  pass pushes overlapping roots apart.
* Every other topic is packed inside the disc of its **primary parent**: the parent whose subtree
  (outside the topic's own) shares the most confidence-weighted works with the topic. Its other
  parents are kept as ``ghost_parents`` for the map's ghost links.
* Sizes: a root's radius is ``root_radius * sqrt(volume / largest root volume)``; the children of a
  disc share one scale factor so that their packing fits in ``fill`` of the parent's radius. Area
  therefore follows volume among siblings, and the parent disc is the unit across parents.

The same inputs always give the same positions (seeded, no set or dict order dependence).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pyarrow as pa

from flatatlas.aggregate.config import ForceAtlasConfig, LayoutConfig
from flatatlas.aggregate.membership import TopicGraph

SCHEMA = pa.schema(
    [
        ("topic_id", pa.string()),
        ("parent_id", pa.string()),
        ("level", pa.int16()),
        ("x", pa.float32()),
        ("y", pa.float32()),
        ("r", pa.float32()),
        ("year", pa.int16()),  # null: the all-time layout (per-year radii are P5-01)
        ("volume", pa.float32()),
        ("ghost_parents", pa.list_(pa.string())),
    ]
)


@dataclass(frozen=True)
class Node:
    topic: int
    parent: int | None  # primary parent
    ghosts: tuple[int, ...]
    x: float
    y: float
    r: float


# -- primary parents -----------------------------------------------------------------------------


def primary_parents(
    graph: TopicGraph, base: np.ndarray, m: np.ndarray, volume: np.ndarray
) -> dict[int, int]:
    """Primary parent of every topic that has parents.

    The score of parent *p* for topic *t* is the sum over works of ``min(m[w, t], evidence[w])``,
    where the evidence is the largest non-derived confidence a work has in *p*'s subtree outside
    *t*'s own subtree (*p* itself included). Ties go to the parent with the larger volume, then to
    the smaller topic ID.
    """
    desc = graph.descendants
    chosen: dict[int, int] = {}
    for t, ps in enumerate(graph.parents):
        if not ps:
            continue
        if len(ps) == 1:
            chosen[t] = ps[0]
            continue
        own = desc[t] | {t}
        scored = []
        for p in ps:
            others = sorted((desc[p] | {p}) - own)
            evidence = base[:, others].max(axis=1) if others else np.zeros(base.shape[0])
            score = float(np.minimum(m[:, t], evidence).sum())
            scored.append((-score, -float(volume[p]), graph.ids[p], p))
        chosen[t] = min(scored)[3]
    return chosen


# -- circle packing ------------------------------------------------------------------------------


def _tangent_points(a, b, ra, rb):
    """Centres at distance ``ra`` from ``a`` and ``rb`` from ``b`` (0, 1 or 2 points)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    d = math.hypot(dx, dy)
    if d == 0 or d > ra + rb or d < abs(ra - rb):
        return []
    x = (ra * ra - rb * rb + d * d) / (2 * d)
    h2 = ra * ra - x * x
    h = math.sqrt(max(h2, 0.0))
    ux, uy = dx / d, dy / d
    px, py = a[0] + x * ux, a[1] + x * uy
    return [(px - h * uy, py + h * ux), (px + h * uy, py - h * ux)]


def pack_circles(radii: Sequence[float], pad: float) -> tuple[list[tuple[float, float]], float]:
    """Greedy deterministic packing: biggest first, each circle at the free tangent spot nearest
    the origin. Returns the centres (around the area-weighted centroid) and the radius of a
    circle around that centroid that holds them all."""
    n = len(radii)
    if n == 0:
        return [], 0.0
    order = sorted(range(n), key=lambda i: (-radii[i], i))
    placed: list[tuple[float, float, float, int]] = []
    for i in order:
        r = radii[i]
        if not placed:
            placed.append((0.0, 0.0, r, i))
            continue
        cands: list[tuple[float, float]] = []
        if len(placed) == 1:
            x0, y0, r0, _ = placed[0]
            cands.append((x0 + r0 + r + pad, y0))
        for a in range(len(placed)):
            for b in range(a + 1, len(placed)):
                pa_, pb_ = placed[a], placed[b]
                cands += _tangent_points(
                    (pa_[0], pa_[1]), (pb_[0], pb_[1]), pa_[2] + r + pad, pb_[2] + r + pad
                )
        free = [
            c
            for c in cands
            if all(math.hypot(c[0] - q[0], c[1] - q[1]) >= q[2] + r + pad - 1e-9 for q in placed)
        ]
        if not free:  # cannot happen with two or more circles; keep a safe fallback
            free = [(max(q[0] + q[2] for q in placed) + r + pad, 0.0)]
        best = min(free, key=lambda c: (c[0] * c[0] + c[1] * c[1], c[0], c[1]))
        placed.append((best[0], best[1], r, i))
    area = sum(q[2] ** 2 for q in placed)
    cx = sum(q[2] ** 2 * q[0] for q in placed) / area
    cy = sum(q[2] ** 2 * q[1] for q in placed) / area
    enclose = max(math.hypot(q[0] - cx, q[1] - cy) + q[2] for q in placed)
    centres = [(0.0, 0.0)] * n
    for x, y, _r, i in placed:
        centres[i] = (x - cx, y - cy)
    return centres, enclose


# -- ForceAtlas2-style layout of the roots --------------------------------------------------


def force_atlas(
    weights: np.ndarray, radii: np.ndarray, cfg: ForceAtlasConfig, seed: int
) -> np.ndarray:
    """Positions (n x 2) of discs with the given radii, pulled together by ``weights`` (n x n)."""
    n = len(radii)
    if n <= 1:
        return np.zeros((n, 2))
    unit = float(radii.mean())
    rad = radii / unit
    gap = cfg.overlap_gap / unit
    w = weights / weights.max() if weights.max() > 0 else weights.copy()
    w = w * cfg.edge_weight_influence
    mass = (weights > 0).sum(axis=1) + 1.0
    mass = mass / mass.mean()  # relative degree weights keep the forces at one scale
    mm = np.outer(mass, mass)
    rng = np.random.default_rng(seed)
    angle = 2 * np.pi * (np.arange(n) + rng.uniform(-0.25, 0.25, n)) / n
    ring = 1.2 * rad.sum() / np.pi
    pos = ring * np.stack([np.cos(angle), np.sin(angle)], axis=1)
    sum_r = rad[:, None] + rad[None, :]
    for it in range(cfg.iterations):
        cool = 1.0 - it / cfg.iterations
        diff = pos[:, None, :] - pos[None, :, :]
        dist = np.sqrt((diff**2).sum(axis=2))
        np.fill_diagonal(dist, 1.0)
        direction = diff / dist[..., None]
        free = dist - sum_r - gap
        rep = np.where(free > 0, cfg.scaling * mm / np.maximum(free, 1e-3), cfg.scaling * mm * 10.0)
        att = w * np.maximum(free, 0.0)
        np.fill_diagonal(rep, 0.0)
        np.fill_diagonal(att, 0.0)
        force = (direction * (rep - att)[..., None]).sum(axis=1)
        norm = np.sqrt((pos**2).sum(axis=1, keepdims=True))
        force -= cfg.gravity * mass[:, None] * pos / np.maximum(norm, 1e-6)
        step = (force / mass[:, None]) * (0.15 * cool + 0.01)
        length = np.sqrt((step**2).sum(axis=1, keepdims=True))
        step *= np.minimum(1.0, 0.5 / np.maximum(length, 1e-9))
        pos = pos + step
    return pos * unit


def separate(pos: np.ndarray, radii: np.ndarray, gap: float, rounds: int = 2000) -> np.ndarray:
    """Push overlapping discs apart (in index order, so the result is reproducible)."""
    pos = pos.copy()
    n = len(radii)
    for _ in range(rounds):
        moved = False
        for i in range(n):
            for j in range(i + 1, n):
                d = pos[j] - pos[i]
                dist = float(np.hypot(d[0], d[1]))
                need = radii[i] + radii[j] + gap
                if dist < need - 1e-9:
                    if dist == 0:
                        d, dist = np.array([1.0, 0.0]), 1.0
                    shift = (need - dist) / 2 * d / dist
                    pos[i] -= shift
                    pos[j] += shift
                    moved = True
        if not moved:
            break
    return pos


# -- the whole layout ----------------------------------------------------------------------------


def compute_layout(
    graph: TopicGraph,
    volume: np.ndarray,
    primary: dict[int, int],
    lateral: Sequence[tuple[int, int, float]],
    cfg: LayoutConfig,
) -> list[Node]:
    """Nodes for every topic. ``lateral`` holds ``(topic, topic, strength)`` for the springs."""
    n = graph.n
    kids: list[list[int]] = [[] for _ in range(n)]
    for t, p in primary.items():
        kids[p].append(t)
    roots = [t for t in range(n) if not graph.parents[t]]

    def top_of(t: int) -> int:
        while t in primary:
            t = primary[t]
        return t

    def sizes(ts: list[int]) -> list[float]:
        s = [math.sqrt(max(float(volume[t]), 0.0)) for t in ts]
        top = max(s) if s else 0.0
        floor = cfg.min_radius_share * top if top > 0 else 1.0
        return [max(x, floor) for x in s]

    s_root = sizes(roots)
    scale = cfg.root_radius / max(s_root)
    r_root = np.array([x * scale for x in s_root])
    index_of = {t: i for i, t in enumerate(roots)}
    w = np.zeros((len(roots), len(roots)))
    for a, b, strength in lateral:
        ra, rb = index_of.get(top_of(a)), index_of.get(top_of(b))
        if ra is not None and rb is not None and ra != rb:
            w[ra, rb] += strength
            w[rb, ra] += strength
    pos = force_atlas(w, r_root, cfg.fa2, cfg.seed)
    pos = separate(pos, r_root, cfg.fa2.overlap_gap)
    pos = pos - pos.mean(axis=0) if len(pos) else pos

    nodes: dict[int, Node] = {}
    queue: list[tuple[int, float, float, float]] = []
    for i, t in enumerate(roots):
        nodes[t] = Node(t, None, (), float(pos[i, 0]), float(pos[i, 1]), float(r_root[i]))
        queue.append((t, nodes[t].x, nodes[t].y, nodes[t].r))
    while queue:
        t, x, y, r = queue.pop(0)
        children = sorted(kids[t], key=lambda c: graph.ids[c])
        if not children:
            continue
        s = sizes(children)
        pad = cfg.pad * min(s)
        centres, enclose = pack_circles(s, pad)
        k = cfg.fill * r / enclose
        for c, (ox, oy), sc in zip(children, centres, s, strict=True):
            ghosts = tuple(p for p in graph.parents[c] if p != t)
            nodes[c] = Node(c, t, ghosts, x + ox * k, y + oy * k, sc * k)
            queue.append((c, nodes[c].x, nodes[c].y, nodes[c].r))
    return [nodes[t] for t in range(n)]


def layout_table(
    graph: TopicGraph, nodes: Sequence[Node], volume: np.ndarray, decimals: int
) -> pa.Table:
    levels = graph.levels
    rows = {name: [] for name in SCHEMA.names}
    for node in nodes:
        t = node.topic
        rows["topic_id"].append(graph.ids[t])
        rows["parent_id"].append(None if node.parent is None else graph.ids[node.parent])
        rows["level"].append(int(levels[t]))
        rows["x"].append(round(node.x, decimals))
        rows["y"].append(round(node.y, decimals))
        rows["r"].append(round(node.r, decimals))
        rows["year"].append(None)
        rows["volume"].append(round(float(volume[t]), 4))
        rows["ghost_parents"].append([graph.ids[g] for g in node.ghosts])
    return pa.Table.from_pydict(rows, schema=SCHEMA)
