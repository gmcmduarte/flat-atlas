"""Conference and journal versions of one work (PLAN §8.2).

Candidate pairs share an author, are a few years apart and sit in different editions. A pair is
scored from the title (after removing "extended abstract" and the like), the author sets, the
SPECTER2 cosine and one "extra" signal (same external record, the later version cites the earlier,
special issue). A score of ``merge_min`` or more merges; between ``report_min`` and ``merge_min``
the pair is listed and left apart; below, it is ignored. Two kinds of pair are never merged by
score: two papers of one edition (a volume does not print a work twice) and titles that carry
different part numbers ("... I" and "... II"). A DOI shared by two papers merges them outright.

Pure functions over ``VersionRef``: the pilot corpus has few journal versions, so the logic is
tested on synthetic pairs and the stage feeds it whatever versions exist.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import combinations

from flatatlas.resolve.config import VersionsConfig
from flatatlas.resolve.text import (
    cosine,
    jaccard,
    normalise_doi,
    numbering_differs,
    title_similarity,
)

KIND_RANK = {"journal": 0, "proceedings": 1, "preprint": 2}


@dataclass(frozen=True)
class VersionRef:
    """What the scorer needs to know about one published version."""

    key: str  # unique and stable (the DBLP key in the pilot)
    title: str
    year: int
    venue_id: str
    edition_id: str | None
    kind: str  # journal | proceedings | preprint
    authors: frozenset[str]  # resolved author keys (DBLP PIDs)
    doi: str | None = None
    embedding: tuple[float, ...] | None = None
    external: frozenset[tuple[str, str]] = frozenset()  # ("s2", corpus id), ("openalex", id)
    named_keys: frozenset[str] = frozenset()  # other DBLP keys the S2 record lists for this paper
    cites: frozenset[str] = frozenset()  # keys of versions this one cites
    special_issue_of: str | None = None  # venue this version's venue is a special issue of


@dataclass(frozen=True)
class PairScore:
    earlier: str
    later: str
    score: float
    verdict: str  # merge | uncertain | ignored | vetoed
    method: str  # doi | scored-pair
    features: dict[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


def _embedding_feature(a: VersionRef, b: VersionRef, floor: float) -> float:
    if a.embedding is None or b.embedding is None:
        return 0.0
    return min(1.0, max(0.0, (cosine(a.embedding, b.embedding) - floor) / (1.0 - floor)))


def _extra_feature(a: VersionRef, b: VersionRef, cfg: VersionsConfig) -> tuple[float, str]:
    """The strongest extra signal and its name; ``a`` is the earlier version, ``b`` the later."""
    values = cfg.extra_values
    best, name = 0.0, ""
    # Authors cite their own earlier papers all the time, so "cites" and "special issue" only
    # count when the later version is a different kind of publication (a journal article after a
    # conference paper), which is what §8.2 describes.
    cross_kind = a.kind != b.kind
    for value, label, holds in (
        (values.same_external_record, "same_external_record", bool(a.external & b.external)),
        (
            values.external_record_names_other,
            "external_record_names_other",
            a.key in b.named_keys or b.key in a.named_keys,
        ),
        (values.cites, "cites", cross_kind and (a.key in b.cites or b.key in a.cites)),
        (
            values.special_issue,
            "special_issue",
            cross_kind and b.special_issue_of is not None and b.special_issue_of == a.venue_id,
        ),
    ):
        if holds and value > best:
            best, name = value, label
    return best, name


def order_pair(a: VersionRef, b: VersionRef) -> tuple[VersionRef, VersionRef]:
    """Earlier version first; ties broken by kind (proceedings before journal) then key."""
    ka = (a.year, -KIND_RANK.get(a.kind, 9), a.key)
    kb = (b.year, -KIND_RANK.get(b.kind, 9), b.key)
    return (a, b) if ka <= kb else (b, a)


def score_pair(a: VersionRef, b: VersionRef, cfg: VersionsConfig) -> PairScore:
    """Score two versions. The verdict follows ``merge_min`` and ``report_min``."""
    a, b = order_pair(a, b)
    doi_a, doi_b = normalise_doi(a.doi), normalise_doi(b.doi)
    if doi_a and doi_a == doi_b:
        return PairScore(a.key, b.key, 1.0, "merge", "doi", {"doi": 1.0}, ("same DOI",))

    title = title_similarity(a.title, b.title, cfg.strip_title_markers)
    authors = jaccard(a.authors, b.authors)
    embedding = _embedding_feature(a, b, cfg.embedding_floor)
    extra, extra_name = _extra_feature(a, b, cfg)
    w = cfg.weights
    score = w.title * title + w.authors * authors + w.embedding * embedding + w.extra * extra
    features = {"title": title, "authors": authors, "embedding": embedding, "extra": extra}
    reasons = [f"extra: {extra_name}"] if extra_name else []

    vetoes = []
    if a.edition_id is not None and a.edition_id == b.edition_id:
        vetoes.append("same edition")
    if numbering_differs(a.title, b.title):
        vetoes.append("different part numbers in the titles")
    if vetoes:
        return PairScore(a.key, b.key, score, "vetoed", "scored-pair", features, tuple(vetoes))
    if score >= cfg.merge_min:
        verdict = "merge"
    elif score >= cfg.report_min:
        verdict = "uncertain"
    else:
        verdict = "ignored"
    return PairScore(a.key, b.key, score, verdict, "scored-pair", features, tuple(reasons))


def candidate_pairs(
    versions: Sequence[VersionRef], cfg: VersionsConfig
) -> Iterable[tuple[VersionRef, VersionRef]]:
    """Pairs worth scoring (PLAN §8.2), each once, earlier version first."""
    by_author: dict[str, list[VersionRef]] = defaultdict(list)
    by_doi: dict[str, list[VersionRef]] = defaultdict(list)
    for v in versions:
        for author in v.authors:
            by_author[author].append(v)
        doi = normalise_doi(v.doi)
        if doi:
            by_doi[doi].append(v)
    seen: set[tuple[str, str]] = set()
    cand = cfg.candidate

    def emit(a: VersionRef, b: VersionRef) -> tuple[VersionRef, VersionRef] | None:
        a, b = order_pair(a, b)
        pair = (a.key, b.key)
        if a.key == b.key or pair in seen:
            return None
        seen.add(pair)
        return a, b

    for group in by_doi.values():
        for a, b in combinations(group, 2):
            if (pair := emit(a, b)) is not None:
                yield pair
    for group in by_author.values():
        for a, b in combinations(group, 2):
            a, b = order_pair(a, b)
            if not 0 <= b.year - a.year <= cand.max_year_gap:
                continue
            if len(a.authors & b.authors) < cand.shared_authors_min:
                continue
            if title_similarity(a.title, b.title, cfg.strip_title_markers) < cand.title_min:
                continue
            if (pair := emit(a, b)) is not None:
                yield pair


@dataclass
class Grouping:
    """Which versions form one work, and what was decided about every pair that was scored."""

    group_of: dict[str, str]  # version key -> group id (the key of the group's earliest version)
    attach: dict[str, PairScore]  # non-founder version key -> its best accepted pair
    pairs: list[PairScore]
    blocked: list[PairScore]  # merges refused because the group already held that edition


def group_versions(
    versions: Sequence[VersionRef], pairs: Iterable[PairScore], cfg: VersionsConfig
) -> Grouping:
    """Union the merging pairs, best score first, never putting two versions of one edition in a
    group (except for a shared DOI, which is the same record twice)."""
    by_key = {v.key: v for v in versions}
    parent = {v.key: v.key for v in versions}
    editions: dict[str, set[str]] = {
        v.key: ({v.edition_id} if v.edition_id else set()) for v in versions
    }

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    all_pairs = sorted(pairs, key=lambda p: (-p.score, p.earlier, p.later))
    accepted: list[PairScore] = []
    blocked: list[PairScore] = []
    for pair in all_pairs:
        if pair.verdict != "merge":
            continue
        ra, rb = find(pair.earlier), find(pair.later)
        if ra == rb:
            accepted.append(pair)
            continue
        if pair.method != "doi" and editions[ra] & editions[rb]:
            blocked.append(pair)
            continue
        parent[rb] = ra
        editions[ra] |= editions[rb]
        accepted.append(pair)

    members: dict[str, list[str]] = defaultdict(list)
    for key in parent:
        members[find(key)].append(key)
    group_of: dict[str, str] = {}
    for keys in members.values():
        founder = min(keys, key=lambda k: _founder_key(by_key, k))
        for key in keys:
            group_of[key] = founder

    attach: dict[str, PairScore] = {}
    for pair in accepted:  # best score first
        for key in (pair.later, pair.earlier):
            if group_of[key] != key and key not in attach:
                attach[key] = pair
    return Grouping(group_of, attach, all_pairs, blocked)


def _founder_key(by_key: dict[str, VersionRef], key: str) -> tuple[int, int, str]:
    v = by_key[key]
    return (v.year, -KIND_RANK.get(v.kind, 9), v.key)


def primary_version(versions: Iterable[VersionRef]) -> VersionRef:
    """The version shown by default: journal over proceedings over preprint, then one with a
    DOI, then the earliest (PLAN §4.2)."""
    return min(
        versions,
        key=lambda v: (KIND_RANK.get(v.kind, 9), 0 if v.doi else 1, v.year, v.key),
    )
