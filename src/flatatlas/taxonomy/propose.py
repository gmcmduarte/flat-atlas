"""``taxonomy propose``: candidate topics and parent links with evidence (PLAN §9.1 steps 4 and 5).

Candidates come from two places: **mined phrases** (a phrase held by at least ``min_topic_size``
works' own title, abstract or TLDR; phrases on nearly the same works are one topic with aliases)
and **clusters** that no phrase topic already covers. Seeds are attached as cross-references
(MSC and CCS by name overlap, OpenAlex topics by the primary topic of the topic's works).

A parent link needs ``min_link_score`` points of evidence, from the five kinds of PLAN §9.1 step 4:

=========================  =======  ==================================================
evidence                   points   rule
=========================  =======  ==================================================
``subsumption`` (b)        2.0      P(parent | child) >= 0.7 and P(child | parent) < 0.5
``seed-structure`` (a)     1.5      the topics' CCS concepts are child and parent
``head`` (c)               1.0/0.5  the parent's phrase ends (1.0) or sits inside (0.5) the child's
``nested-clusters`` (d)    1.0      a cluster of the child lies inside a cluster of the parent
``citation`` (e)           0.5      the child cites the parent's works much more than the reverse
=========================  =======  ==================================================

A topic left without a parent joins the larger topic that holds at least ``soft_attach_containment``
of its works (marked ``soft``), so the roots are few. Everything is deterministic: sorted
iteration and ties broken by key; no randomness enters this step.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from flatatlas.taxonomy.check import check_topics
from flatatlas.taxonomy.config import ProposeConfig
from flatatlas.taxonomy.mine import PhraseStats
from flatatlas.taxonomy.phrases import fold, key_of, key_tokens
from flatatlas.taxonomy.schema import TopicEntry, TopicsFile, normalise_phrase, topic_levels
from flatatlas.text.composite import CompositeParts

W_SUBSUMPTION = 2.0
W_SEED_STRUCTURE = 1.5
W_HEAD_SUFFIX = 1.0
W_HEAD_INSIDE = 0.5
W_NESTED = 1.0
W_CITATION = 0.5
CLUSTER_SCORE_FACTOR = 0.8
SEED_JACCARD = 0.34
OPENALEX_SHARE = 0.25
CITATION_MIN_EDGES = 3


@dataclass
class Inputs:
    """Everything propose reads, as plain data (so tests need no warehouse)."""

    parts: Sequence[CompositeParts]
    phrase_rows: Sequence[Mapping[str, Any]]
    stats: Mapping[str, PhraseStats]
    clusters: Sequence[Mapping[str, Any]]
    members: Sequence[Mapping[str, Any]]
    citations: Sequence[tuple[str, str]] = ()
    cited_by: Mapping[str, int] = field(default_factory=dict)
    openalex_primary: Mapping[str, tuple[str, str]] = field(default_factory=dict)  # id, name
    seeds: Sequence[Mapping[str, Any]] = ()  # scheme, id, label, parents (ccs)
    taxonomy_version: int = 1
    config_hash: str = ""


@dataclass
class Candidate:
    cid: str
    name: str
    origin: str
    works: frozenset[int]
    score: float
    aliases: list[str] = field(default_factory=list)
    phrase_keys: list[str] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)
    cluster_matches: list[dict[str, Any]] = field(default_factory=list)
    seed_matches: list[dict[str, Any]] = field(default_factory=list)
    openalex: list[dict[str, Any]] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)  # accepted parent links
    specificity: float | None = None
    topic_id: str = ""

    @property
    def key_token_sets(self) -> list[tuple[str, ...]]:
        names = [self.name, *self.aliases]
        return [t for t in (key_tokens(n) for n in names) if t]


@dataclass
class Result:
    file: TopicsFile
    candidates: list[Candidate]
    work_ids: list[str]
    unmatched_seeds: list[Mapping[str, Any]]
    problems: list[str]
    stats: dict[str, Any]


def jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def capitalise(text: str) -> str:
    return text[:1].upper() + text[1:]


# -- candidates -----------------------------------------------------------------------------------


def phrase_candidates(
    inputs: Inputs, index: Mapping[str, int], cfg: ProposeConfig
) -> list[Candidate]:
    suggestions = {
        r["key"]: {s["phrase"] for s in (r.get("merge_suggestions") or [])}
        for r in inputs.phrase_rows
    }
    excluded = {key_of(p) for p in cfg.exclude_phrases}
    out: list[Candidate] = []
    for row in inputs.phrase_rows:
        if row["source"] != "text" or row["key"] in excluded:
            continue
        s = inputs.stats.get(row["key"])
        if s is None or (row["specificity"] or 0) < cfg.min_specificity:
            continue
        if row["n_tokens"] == 1 and row["specificity"] < cfg.min_unigram_specificity:
            continue  # a single common word ("finite", "system") is not a topic
        if row["n_tokens"] == 1 and row["key"].endswith(("ed", "ly")):
            continue  # a participle or an adverb ("accepted", "finitely")
        works = frozenset(index[w] for w in s.in_own if w in index)
        if len(works) < cfg.min_topic_size:
            continue
        out.append(
            Candidate(
                cid=row["key"],
                name=row["phrase"],
                origin="mined",
                works=works,
                score=float(row["score"]),
                phrase_keys=[row["key"]],
                variants=list(row["variants"]),
                specificity=float(row["specificity"]),
            )
        )
    out.sort(key=lambda c: (-c.score, c.cid))
    return _merge_synonyms(out, cfg, suggestions)


def _merge_synonyms(
    cands: list[Candidate], cfg: ProposeConfig, suggestions: Mapping[str, set[str]]
) -> list[Candidate]:
    """Fold a candidate into an earlier (better scored) one on (nearly) the same works."""
    kept: list[Candidate] = []
    for cand in cands:
        target = None
        for other in kept:
            jac = jaccard(cand.works, other.works)
            suggested = cand.name in suggestions.get(other.cid, ()) or other.name in (
                suggestions.get(cand.cid, ())
            )
            if jac >= cfg.synonym_jaccard or (suggested and jac >= 0.6):
                target = other
                break
        if target is None:
            kept.append(cand)
            continue
        target.aliases.append(cand.name)
        target.phrase_keys.extend(cand.phrase_keys)
        target.variants.extend(cand.variants)
    return kept


def cluster_candidates(
    inputs: Inputs,
    index: Mapping[str, int],
    phrase_cands: list[Candidate],
    cfg: ProposeConfig,
) -> tuple[list[Candidate], dict[str, str]]:
    """Clusters no phrase topic covers become candidates. Returns them and ``cluster id -> cid``."""
    by_cluster: dict[str, set[int]] = defaultdict(set)
    for m in inputs.members:
        if m["work_id"] in index:
            by_cluster[m["cluster_id"]].add(index[m["work_id"]])
    covering: dict[str, str] = {}
    new: list[Candidate] = []
    used: set[str] = {key_of(n) for c in phrase_cands for n in (c.name, *c.aliases, *c.variants)}
    # coarse to fine, larger first: the largest version of a cluster names the candidate
    ordered = sorted(
        inputs.clusters, key=lambda c: (-c["granularity"], -c["size"], c["cluster_id"])
    )
    for cl in ordered:
        works = frozenset(by_cluster.get(cl["cluster_id"], ()))
        if len(works) < cfg.min_topic_size:
            continue
        best, best_j = None, 0.0
        for cand in [*phrase_cands, *new]:
            j = jaccard(works, cand.works)
            if j > best_j or (j == best_j and best is not None and cand.cid < best.cid):
                best, best_j = cand, j
        if best is not None and best_j >= cfg.cluster_match_jaccard:
            best.cluster_matches.append({"cluster": cl["cluster_id"], "jaccard": round(best_j, 3)})
            covering[cl["cluster_id"]] = best.cid
            continue
        shown = [inputs.stats[t].surface if t in inputs.stats else t for t in cl["terms"]]
        free = [t for t in shown if key_of(t) not in used]
        if not free:
            continue  # every label term already names a phrase topic: nothing new to propose
        used.update(key_of(t) for t in free[:3])
        cand = Candidate(
            cid=cl["cluster_id"],
            name=free[0],
            origin="cluster",
            works=works,
            score=CLUSTER_SCORE_FACTOR * math.log1p(len(works)),
            aliases=free[1:3],
            variants=[],
            cluster_matches=[{"cluster": cl["cluster_id"], "jaccard": 1.0}],
            examples=list(cl["examples"]),
        )
        new.append(cand)
        covering[cl["cluster_id"]] = cand.cid
    return new, covering


# -- seeds ----------------------------------------------------------------------------------------


def match_seeds(
    cands: Sequence[Candidate], seeds: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    """Attach MSC and CCS entries to topics by name overlap; return the seeds nothing matched."""
    matched: set[tuple[str, str]] = set()
    for seed in seeds:
        seed_tokens = set(key_tokens(seed["label"]))
        if not seed_tokens:
            continue
        for cand in cands:
            best = 0.0
            for tokens in cand.key_token_sets:
                t = set(tokens)
                jac = len(t & seed_tokens) / len(t | seed_tokens)
                if len(tokens) >= 2 and t <= seed_tokens:
                    jac = max(jac, 0.5)
                best = max(best, jac)
            if best >= SEED_JACCARD:
                cand.seed_matches.append(
                    {"scheme": seed["scheme"], "id": seed["id"], "label": seed["label"],
                     "jaccard": round(best, 3)}
                )  # fmt: skip
                matched.add((seed["scheme"], seed["id"]))
    for cand in cands:
        cand.seed_matches.sort(key=lambda m: (-m["jaccard"], m["scheme"], m["id"]))
        cand.seed_matches = cand.seed_matches[:4]
    return [s for s in seeds if (s["scheme"], s["id"]) not in matched]


def attach_openalex(
    cands: Sequence[Candidate],
    work_ids: Sequence[str],
    primary: Mapping[str, tuple[str, str]],
) -> None:
    for cand in cands:
        counts: Counter[tuple[str, str]] = Counter(
            primary[work_ids[i]] for i in cand.works if work_ids[i] in primary
        )
        total = len(cand.works)
        cand.openalex = [
            {"id": tid, "name": name, "share": round(n / total, 3)}
            for (tid, name), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            if n / total >= OPENALEX_SHARE
        ][:3]


# -- links ----------------------------------------------------------------------------------------


def _head_points(child: Candidate, parent: Candidate) -> float:
    best = 0.0
    for ct in child.key_token_sets:
        for pt in parent.key_token_sets:
            if len(pt) >= len(ct):
                continue
            if ct[-len(pt) :] == pt:
                best = max(best, W_HEAD_SUFFIX)
            elif any(ct[i : i + len(pt)] == pt for i in range(len(ct) - len(pt) + 1)):
                best = max(best, W_HEAD_INSIDE)
    return best


def _cluster_ancestors(clusters: Sequence[Mapping[str, Any]]) -> dict[str, set[str]]:
    parent = {c["cluster_id"]: c.get("parent_cluster") for c in clusters}
    out: dict[str, set[str]] = {}
    for cid in parent:
        chain, cur = set(), parent.get(cid)
        while cur and cur not in chain:
            chain.add(cur)
            cur = parent.get(cur)
        out[cid] = chain
    return out


def _citation_counts(
    cands: Sequence[Candidate], work_ids: Sequence[str], citations: Sequence[tuple[str, str]]
) -> tuple[dict[tuple[int, int], int], dict[int, int]]:
    """``(child index, parent index) -> edges`` and ``child index -> total edges out``."""
    position = {w: i for i, w in enumerate(work_ids)}
    holders: dict[int, list[int]] = defaultdict(list)
    for ci, cand in enumerate(cands):
        for w in cand.works:
            holders[w].append(ci)
    edges: dict[tuple[int, int], int] = defaultdict(int)
    out_total: dict[int, int] = defaultdict(int)
    for citing, cited in citations:
        a, b = position.get(citing), position.get(cited)
        if a is None or b is None:
            continue
        for ci in holders.get(a, ()):
            out_total[ci] += 1
            for cj in holders.get(b, ()):
                edges[(ci, cj)] += 1
    return edges, out_total


def find_links(
    cands: list[Candidate],
    inputs: Inputs,
    work_ids: Sequence[str],
    covering: Mapping[str, str],
    cfg: ProposeConfig,
) -> dict[str, list[dict[str, Any]]]:
    """Scored parent links per child cid (``score >= min_link_score``), best first."""
    ancestors = _cluster_ancestors(inputs.clusters)
    cluster_owner = dict(covering)  # cluster id -> cid
    cites, out_total = _citation_counts(cands, work_ids, inputs.citations)
    ccs_parents = {
        s["id"]: set(s.get("parents") or []) for s in inputs.seeds if s["scheme"] == "ccs"
    }
    links: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ci, child in enumerate(cands):
        child_ccs = {m["id"] for m in child.seed_matches if m["scheme"] == "ccs"}
        child_clusters = {m["cluster"] for m in child.cluster_matches}
        for pi, parent in enumerate(cands):
            if ci == pi or len(parent.works) <= len(child.works):
                continue
            inter = len(child.works & parent.works)
            evidence: dict[str, float] = {}
            p_given_c = inter / len(child.works)
            c_given_p = inter / len(parent.works)
            if (
                p_given_c >= cfg.subsumption_parent_given_child
                and c_given_p < cfg.subsumption_child_given_parent
            ):
                evidence["subsumption"] = W_SUBSUMPTION
            if child_ccs and any(
                ccs_parents.get(c, set())
                & {m["id"] for m in parent.seed_matches if m["scheme"] == "ccs"}
                for c in child_ccs
            ):  # noqa: E501
                evidence["seed-structure"] = W_SEED_STRUCTURE
            head = _head_points(child, parent)
            if head:
                evidence["head"] = head
            parent_clusters = {m["cluster"] for m in parent.cluster_matches}
            if any(
                cluster_owner.get(anc) == parent.cid or anc in parent_clusters
                for cl in child_clusters
                for anc in ancestors.get(cl, ())
            ):
                evidence["nested-clusters"] = W_NESTED
            n_edges = cites.get((ci, pi), 0)
            if (
                n_edges >= CITATION_MIN_EDGES
                and out_total.get(ci)
                and n_edges / out_total[ci] >= cfg.citation_min_share
                and n_edges >= 2 * cites.get((pi, ci), 0)
            ):
                evidence["citation"] = W_CITATION
            score = sum(evidence.values())
            if score >= cfg.min_link_score:
                links[child.cid].append(
                    {
                        "parent": parent.cid,
                        "score": round(score, 2),
                        "evidence": dict(sorted(evidence.items())),
                        "p_parent_given_child": round(p_given_c, 3),
                        "p_child_given_parent": round(c_given_p, 3),
                        "soft": False,
                    }
                )
    for lst in links.values():
        lst.sort(key=lambda link: (-link["score"], link["parent"]))
    return links


def reduce_links(
    links: Mapping[str, list[dict[str, Any]]], cands: Sequence[Candidate], cfg: ProposeConfig
) -> dict[str, list[dict[str, Any]]]:
    """Keep at most ``max_parents`` parents per child and drop a parent that is an ancestor of
    another kept parent (transitive reduction). Parents are strictly larger, so no cycle exists."""
    size = {c.cid: len(c.works) for c in cands}
    accepted = {child: [lk["parent"] for lk in lst] for child, lst in links.items()}

    def ancestors(cid: str) -> set[str]:
        seen: set[str] = set()
        stack = list(accepted.get(cid, []))
        while stack:
            cur = stack.pop()
            if cur not in seen:
                seen.add(cur)
                stack.extend(accepted.get(cur, []))
        return seen

    out: dict[str, list[dict[str, Any]]] = {}
    for child, lst in links.items():
        parents = {lk["parent"] for lk in lst}
        redundant = set()
        for p in parents:
            if p in set().union(*(ancestors(q) for q in parents if q != p)):
                redundant.add(p)
        kept = [lk for lk in lst if lk["parent"] not in redundant]
        kept.sort(key=lambda lk: (-lk["score"], -size[lk["parent"]], lk["parent"]))
        out[child] = kept[: cfg.max_parents]
    return out


def soft_attach(
    cands: Sequence[Candidate], accepted: dict[str, list[dict[str, Any]]], cfg: ProposeConfig
) -> int:
    """Give a parentless topic the larger topic holding most of its works (``soft`` links).

    Largest orphans first, and a soft link never points at a topic whose own parent is soft, so
    soft links cannot chain into a deep tree of mere containment.
    """
    n = 0
    ordered = sorted(cands, key=lambda c: (-len(c.works), c.cid))
    soft: set[str] = set()
    for child in ordered:
        if accepted.get(child.cid):
            continue
        best: tuple[float, int, str] | None = None
        best_p: Candidate | None = None
        for parent in ordered:
            if len(parent.works) <= len(child.works) or parent.cid in soft:
                continue
            share = len(child.works & parent.works) / len(child.works)
            if share < cfg.soft_attach_containment:
                continue
            rank = (-share, -len(parent.works), parent.cid)
            if best is None or rank < best:
                best, best_p = rank, parent
        if best_p is not None and best is not None:
            accepted[child.cid] = [
                {
                    "parent": best_p.cid,
                    "score": 0.0,
                    "evidence": {},
                    "p_parent_given_child": round(-best[0], 3),
                    "p_child_given_parent": round(
                        len(child.works & best_p.works) / len(best_p.works), 3
                    ),
                    "soft": True,
                }
            ]
            soft.add(child.cid)
            n += 1
    return n


# -- output ---------------------------------------------------------------------------------------


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", fold(name)).strip("-") or "topic"
    slug, n = base, 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    taken.add(slug)
    return slug


def _pick_examples(cand: Candidate, work_ids: Sequence[str], inputs: Inputs, n: int) -> list[str]:
    if cand.examples:
        return cand.examples[:n]
    keys = set(cand.phrase_keys)
    in_title = {w for k in keys for w in (inputs.stats[k].in_title if k in inputs.stats else ())}
    ranked = sorted(
        (work_ids[i] for i in cand.works),
        key=lambda w: (w not in in_title, -inputs.cited_by.get(w, 0), w),
    )
    return ranked[:n]


def propose(inputs: Inputs, cfg: ProposeConfig) -> Result:
    work_ids = sorted(p.work_id for p in inputs.parts)
    index = {w: i for i, w in enumerate(work_ids)}
    titles = {p.work_id: p.title for p in inputs.parts}

    cands = phrase_candidates(inputs, index, cfg)
    extra, covering = cluster_candidates(inputs, index, cands, cfg)
    for cand in cands:
        for m in cand.cluster_matches:
            covering[m["cluster"]] = cand.cid
    cands = sorted([*cands, *extra], key=lambda c: (-c.score, c.cid))[: cfg.max_topics]
    kept = {c.cid for c in cands}
    covering = {cl: cid for cl, cid in covering.items() if cid in kept}

    unmatched = match_seeds(cands, inputs.seeds)
    attach_openalex(cands, work_ids, inputs.openalex_primary)
    links = find_links(cands, inputs, work_ids, covering, cfg)
    accepted = reduce_links(links, cands, cfg)
    n_soft = soft_attach(cands, accepted, cfg)

    taken: set[str] = set()
    for cand in sorted(cands, key=lambda c: (-c.score, c.cid)):
        cand.topic_id = _slug(cand.name, taken)
        cand.examples = _pick_examples(cand, work_ids, inputs, cfg.examples_per_topic)
        cand.links = accepted.get(cand.cid, [])
    by_cid = {c.cid: c for c in cands}

    phrases = claim_phrases(cands)
    entries = [
        _entry(c, by_cid, titles, inputs, phrases) for c in sorted(cands, key=lambda c: c.topic_id)
    ]
    file = TopicsFile(taxonomy_version=inputs.taxonomy_version, topics=entries)
    levels = topic_levels(file.topics)
    problems = check_topics(file)
    roots = [t.id for t in file.topics if not t.parents]
    stats = {
        "works": len(work_ids),
        "topics": len(entries),
        "mined": sum(c.origin == "mined" for c in cands),
        "cluster": sum(c.origin == "cluster" for c in cands),
        "roots": len(roots),
        "with_scored_parent": sum(1 for c in cands if any(not lk["soft"] for lk in c.links)),
        "with_soft_parent": n_soft,
        "levels": dict(sorted(Counter(levels.values()).items())),
        "with_seed_match": sum(bool(c.seed_matches) for c in cands),
        "unmatched_seeds": len(unmatched),
        "config": inputs.config_hash,
    }
    return Result(
        file, sorted(cands, key=lambda c: c.topic_id), work_ids, unmatched, problems, stats
    )


def claim_phrases(cands: Sequence[Candidate]) -> dict[str, tuple[list[str], list[str]]]:
    """``cid -> (aliases, include_phrases)`` with every phrase owned by exactly one topic.

    Names claim first (best score first), then aliases and variants; a phrase already claimed by
    another topic is left out of this one. (``taxonomy check`` forbids shared phrases.)
    """
    ordered = sorted(cands, key=lambda c: (-c.score, c.cid))
    owner: dict[str, str] = {}
    for cand in ordered:
        owner.setdefault(normalise_phrase(cand.name), cand.cid)
    out: dict[str, tuple[list[str], list[str]]] = {}
    for cand in ordered:
        aliases: list[str] = []
        for alias in [*cand.aliases, *cand.variants]:
            key = normalise_phrase(alias)
            if not key or key == normalise_phrase(cand.name) or alias in aliases:
                continue
            if owner.setdefault(key, cand.cid) == cand.cid:
                aliases.append(alias)
        include = [cand.name, *aliases]
        out[cand.cid] = (aliases, include)
    return out


def _entry(
    cand: Candidate,
    by_cid: Mapping[str, Candidate],
    titles: Mapping[str, str],
    inputs: Inputs,
    phrases: Mapping[str, tuple[list[str], list[str]]],
) -> TopicEntry:
    aliases, include = phrases[cand.cid]
    parents = [by_cid[lk["parent"]].topic_id for lk in cand.links]
    msc = sorted({m["id"] for m in cand.seed_matches if m["scheme"] == "msc"})
    ccs = sorted({m["id"] for m in cand.seed_matches if m["scheme"] == "ccs"})
    return TopicEntry(
        id=cand.topic_id,
        name=capitalise(cand.name),
        aliases=aliases,
        description="",
        parents=parents,
        xref={"ccs": ccs, "msc": msc, "openalex": [o["id"] for o in cand.openalex]},
        include_phrases=include,
        exclude_phrases=[],
        seed_works=[],
        origin=cand.origin,
        reviewed=False,
        status="proposed",
        evidence={
            "size": len(cand.works),
            "score": round(cand.score, 3),
            "specificity": cand.specificity,
            "phrase_keys": cand.phrase_keys,
            "clusters": cand.cluster_matches,
            "seeds": cand.seed_matches,
            "openalex_topics": cand.openalex,
            "parent_links": [{**lk, "parent": by_cid[lk["parent"]].topic_id} for lk in cand.links],
            "examples": [{"work": w, "title": titles.get(w, "")} for w in cand.examples],
        },
    )
