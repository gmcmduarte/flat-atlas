"""The automatic checks of PLAN §9.6 that need no held-out label.

Each function takes plain arrays and dictionaries, so it can be tested on a toy. A *selection map*
is ``{corpus row: Selection}`` from ``fusion.select_tags`` for one variant. Level-0 topic sets of a
work include its derived ancestors, so a work tagged ``dfa`` also counts for ``regular-languages``.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable

import numpy as np

from flatatlas.tagging import noisyor
from flatatlas.tagging.config import TaggerConfig
from flatatlas.tagging.fusion import Selection, select_tags
from flatatlas.tagging.inputs import Corpus, Dag

SelMap = dict[int, Selection]


def select_all(
    probs: dict[int, dict[int, float]], n_works: int, dag: Dag, selection: dict, fallback_min: float
) -> SelMap:
    """The selection of every work (an untagged work has an empty selection with ``untagged``)."""
    return {
        r: select_tags(
            probs.get(r, {}),
            dag,
            threshold=selection["threshold"],
            max_topics=selection["max_topics"],
            fallback_min=fallback_min,
        )
        for r in range(n_works)
    }


def topic_sets(sels: SelMap, dag: Dag, level: int | None = None) -> dict[int, set[int]]:
    """Per work, the topics of its selection rows (derived included), optionally one level."""
    out: dict[int, set[int]] = {}
    for r, s in sels.items():
        out[r] = {t for t, _p, _d in s.rows if level is None or dag.level[t] == level}
    return out


# -- coverage, stability, anchors, venue sanity ---------------------------------------------------


def coverage(sels: SelMap) -> dict[str, float]:
    """``strict``: works with at least one non-derived tag above the threshold; ``any`` adds the
    low-confidence fallback tag. The hard check reads ``strict``."""
    n = max(len(sels), 1)
    strict = sum(1 for s in sels.values() if s.rows and not s.low_confidence)
    anyt = sum(1 for s in sels.values() if s.rows)
    return {"strict": strict / n, "any": anyt / n, "n": float(len(sels))}


def stability(a: SelMap, b: SelMap) -> dict[str, float]:
    """Share of works tagged under run ``a`` whose primary tag is the same under run ``b``."""
    tagged = [r for r, s in a.items() if s.primary is not None]
    same = sum(1 for r in tagged if b.get(r) is not None and b[r].primary == a[r].primary)
    return {"unchanged": same / max(len(tagged), 1), "n": float(len(tagged))}


def venue_sanity(
    sels: SelMap,
    venues: list[str],
    expected: dict[str, list[str]],
    dag: Dag,
    top: int,
) -> dict:
    """Each expected level-0 topic of a venue must be among the venue's ``top`` level-0 topics,
    ranked by the number of the venue's works carrying the topic."""
    by_venue: dict[str, Counter] = defaultdict(Counter)
    n_venue: Counter = Counter()
    for r, s in sels.items():
        v = venues[r]
        n_venue[v] += 1
        for t in {t for t, _p, _d in s.rows if dag.level[t] == 0}:
            by_venue[v][t] += 1
    detail = {}
    met = total = 0
    for venue, topics in expected.items():
        ranked = [t for t, _c in sorted(by_venue[venue].items(), key=lambda kv: (-kv[1], kv[0]))]
        for topic in topics:
            t = dag.index.get(topic)
            rank = ranked.index(t) + 1 if t in ranked else None
            ok = rank is not None and rank <= top
            met += ok
            total += 1
            detail[f"{venue}:{topic}"] = {
                "rank": rank,
                "share": by_venue[venue][t] / max(n_venue[venue], 1) if t is not None else 0.0,
                "ok": ok,
            }
    return {"met": met, "total": total, "rate": met / max(total, 1), "detail": detail}


def anchor_hits(
    items: Iterable[tuple[str, str, int, str]],
    probs: dict[int, dict[int, float]],
    dag: Dag,
    *,
    top: int = 3,
) -> dict:
    """Is each anchor's expected topic among the ``top`` most probable topics of its work?

    ``items`` are ``(anchor id, expected topic id, corpus row, group)``. Returns hit counts per
    group, the pooled ``all`` rate and the list of misses.
    """
    groups: dict[str, list[bool]] = defaultdict(list)
    misses: list[str] = []
    for anchor_id, topic, row, group in items:
        if topic not in dag.index:
            continue
        ranked = sorted(probs.get(row, {}).items(), key=lambda kv: (-kv[1], kv[0]))[:top]
        names = [dag.ids[t] for t, _p in ranked]
        hit = topic in names
        groups[group].append(hit)
        if not hit:
            misses.append(f"{anchor_id} ({group}): expected {topic}, got {', '.join(names)}")
    out = {
        g: {"n": len(h), "hit": sum(h), "rate": sum(h) / max(len(h), 1)} for g, h in groups.items()
    }
    pooled = [x for h in groups.values() for x in h]
    out["all"] = {"n": len(pooled), "hit": sum(pooled), "rate": sum(pooled) / max(len(pooled), 1)}
    return {"groups": out, "misses": misses}


# -- citation consistency, method agreement -------------------------------------------------------


def citation_consistency(sels: SelMap, edges: Iterable[tuple[int, int, bool]], dag: Dag) -> dict:
    """Share of a work's in-corpus references that share a level-0 topic with it (mean over works
    that have at least one tagged in-corpus reference)."""
    l0 = topic_sets(sels, dag, level=0)
    refs: dict[int, list[int]] = defaultdict(list)
    for citing, cited, _ in edges:
        refs[citing].append(cited)
    shares = []
    for r, cited in refs.items():
        mine = l0.get(r, set())
        usable = [c for c in cited if l0.get(c)]
        if mine and usable:
            shares.append(sum(1 for c in usable if mine & l0[c]) / len(usable))
    return {"mean": float(np.mean(shares)) if shares else float("nan"), "n_works": len(shares)}


def family_level0(sig_matrices: dict[str, np.ndarray], dag: Dag, cfg: TaggerConfig) -> dict:
    """Evidence per family on the level-0 topics, rolled up from descendants (works x level-0)."""
    l0 = [t for t in range(dag.n) if dag.level[t] == 0]
    fams = {
        "lexical": ("lex_title", "lex_abstract", "lex_refs"),
        "embedding": ("emb_seed",),
        "source": ("src_openalex",),
    }
    out = {}
    for fam, names in fams.items():
        ev = np.maximum.reduce([noisyor.evidence(n, sig_matrices[n], cfg) for n in names])
        cols = []
        for t in l0:
            members = [t, *dag.descendants(t)]
            cols.append(ev[:, members].max(axis=1))
        out[fam] = np.column_stack(cols)
    return {"l0": l0, "evidence": out}


def method_agreement(fam: dict, dag: Dag, flag_below: float) -> dict:
    """Top-1 level-0 agreement between lexical-only, embedding-only and source-only taggings.

    A work takes part in a pair when both families have some evidence for it. Per topic: the
    Jaccard index of the works family A puts first and the works family B puts first, averaged over
    the three pairs; topics under ``flag_below`` (with some works) are flagged.
    """
    names = list(fam["evidence"])
    top = {}
    for n in names:
        ev = fam["evidence"][n]
        has = ev.max(axis=1) > 0
        top[n] = (np.where(has, ev.argmax(axis=1), -1), has)
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1 :]]
    overall = {}
    per_topic: dict[int, list[float]] = defaultdict(list)
    for a, b in pairs:
        both = top[a][1] & top[b][1]
        overall[f"{a}-{b}"] = {
            "top1_agreement": float((top[a][0][both] == top[b][0][both]).mean())
            if both.any()
            else None,
            "n_works": int(both.sum()),
        }
        for k, t in enumerate(fam["l0"]):
            sa = set(np.flatnonzero((top[a][0] == k) & both))
            sb = set(np.flatnonzero((top[b][0] == k) & both))
            if sa | sb:
                per_topic[t].append(len(sa & sb) / len(sa | sb))
    topics = {dag.ids[t]: float(np.mean(v)) for t, v in per_topic.items()}
    return {
        "pairs": overall,
        "per_topic": topics,
        "flagged": sorted(t for t, v in topics.items() if v < flag_below),
    }


# -- coherence ------------------------------------------------------------------------------------

_STOP_WORDS = (
    "the of and a an in on for to with by from at as is are be its their this that these "
    "those or via over under into using use new two three one some all any each not no "
    "based about between towards toward within without more than"
)
_STOP = frozenset(_STOP_WORDS.split())
_WORD = re.compile(r"[a-z][a-z0-9-]{2,}")


def title_terms(title: str) -> set[str]:
    return {w for w in _WORD.findall(title.lower()) if w not in _STOP}


def coherence(
    sels: SelMap,
    corpus: Corpus,
    dag: Dag,
    *,
    min_works: int = 5,
    top_terms: int = 10,
    seed: int = 0,
) -> dict:
    """Per topic: NPMI of the top title terms, and mean intra-topic cosine against random pairs."""
    docs = [title_terms(p.title) for p in corpus.parts]
    n = len(docs)
    df: Counter = Counter()
    for d in docs:
        df.update(d)
    members: dict[int, list[int]] = defaultdict(list)
    for r, s in sels.items():
        for t, _p, _d in s.rows:
            members[t].append(r)
    rng = np.random.default_rng(seed)
    a, b = rng.integers(0, n, size=(2, 4000))
    keep = a != b
    baseline = float((corpus.vectors[a[keep]] * corpus.vectors[b[keep]]).sum(axis=1).mean())
    out = {}
    for t, rows in members.items():
        if len(rows) < min_works:
            continue
        tf: Counter = Counter()
        for r in rows:
            tf.update(docs[r])
        scored = sorted(
            ((c * math.log(n / df[w]), w) for w, c in tf.items() if df[w] >= 3),
            key=lambda x: (-x[0], x[1]),
        )
        terms = [w for _s, w in scored[:top_terms]]
        npmis = []
        for i, w1 in enumerate(terms):
            for w2 in terms[i + 1 :]:
                co = sum(1 for d in docs if w1 in d and w2 in d)
                if co == 0:
                    npmis.append(-1.0)
                    continue
                p12, p1, p2 = co / n, df[w1] / n, df[w2] / n
                npmis.append(math.log(p12 / (p1 * p2)) / -math.log(p12) if p12 < 1 else 1.0)
        sample = sorted(rows)[:: max(len(rows) // 80, 1)][:80]
        V = corpus.vectors[sample]
        sims = V @ V.T
        iu = np.triu_indices(len(sample), k=1)
        cos = float(sims[iu].mean()) if len(sample) > 1 else float("nan")
        out[dag.ids[t]] = {
            "n": len(rows),
            "npmi": float(np.mean(npmis)) if npmis else float("nan"),
            "cosine": cos,
            "terms": terms,
        }
    return {"baseline_cosine": baseline, "topics": out}


# -- hold-out leak test ---------------------------------------------------------------------------


def leak_sample(work_ids: list[str], eligible: Iterable[int], size: int, seed: int) -> list[int]:
    """A deterministic sample (by hash of the work ID) of ``size`` of the eligible rows."""
    ordered = sorted(
        eligible,
        key=lambda r: hashlib.sha256(f"leak:{seed}:{work_ids[r]}".encode()).hexdigest(),
    )
    return ordered[:size]


def recovery(before: SelMap, after: SelMap, rows: list[int], dag: Dag) -> dict:
    """Of the non-derived tags the rows had before ``lex_title`` was hidden, the share still in
    the selection afterwards (derived rows included), and the share whose primary is unchanged."""
    kept = total = same = n = 0
    for r in rows:
        prev = {t for t, _p, d in before[r].rows if not d}
        now = {t for t, _p, _d in after[r].rows}
        total += len(prev)
        kept += len(prev & now)
        n += 1
        same += int(before[r].primary == after[r].primary)
    return {
        "tags_recovered": kept / max(total, 1),
        "primary_unchanged": same / max(n, 1),
        "n_works": n,
        "n_tags": total,
    }


# -- splits by paper type -------------------------------------------------------------------------


def paper_type(corpus: Corpus, years: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """Group labels per work: has abstract, number of references, decade."""
    has_abs = np.array(
        ["abstract" if p.abstract or p.tldr else "no abstract" for p in corpus.parts]
    )
    refs = np.array(
        [
            "0 references"
            if p.n_references == 0
            else "1-9 references"
            if p.n_references < 10
            else "10+ references"
            for p in corpus.parts
        ]
    )
    dec = np.array(
        [
            f"{int(p.year) // 10 * 10}s" if p.year and str(p.year).isdigit() else "unknown"
            for p in corpus.parts
        ]
    )
    return {"abstract": has_abs, "references": refs, "decade": dec}


def coverage_by_type(sels: SelMap, types: dict[str, np.ndarray]) -> dict:
    out: dict[str, dict[str, dict]] = {}
    for kind, labels in types.items():
        groups: dict[str, list[int]] = defaultdict(list)
        for r in sels:
            groups[str(labels[r])].append(r)
        out[kind] = {
            g: {"n": len(rows), "strict": coverage({r: sels[r] for r in rows})["strict"]}
            for g, rows in sorted(groups.items())
        }
    return out
