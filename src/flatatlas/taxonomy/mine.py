"""``taxonomy mine``: candidate phrases from the composite text (PLAN §9.1 step 2).

1. Extract phrases (``phrases.py``) from each work's title, abstract, TLDR and reference titles.
   A phrase in a reference title counts ``reference_weight`` against 1.0 for the work's own title.
2. Merge variants: same key (case, hyphens, Greek letters, spelling, plurals), and a phrase that
   only adds a generic tail word ("shuffle product" and "shuffle") when both occur.
3. Score by **c-TF-IDF** against a background of titles of non-FLAT theory papers: a phrase is a
   good candidate when it is frequent in the FLAT works and rare in the background.
4. Drop a phrase that is only a part of a longer one with almost the same document frequency.
5. Suggest merges between phrases whose works have nearly the same mean SPECTER2 vector. These
   are suggestions only; nothing is merged on the strength of a vector.
6. OpenAlex keywords are listed with their source, never merged in (D-65).

Everything is deterministic: sorted iteration, ties broken by key, no randomness.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from flatatlas.taxonomy.config import BackgroundConfig, MineConfig
from flatatlas.taxonomy.phrases import extract, fold, key_of
from flatatlas.text.composite import CompositeParts

GENERIC_TAILS = frozenset({"product", "operation", "operator"})  # compared after singularising
MAX_VARIANTS = 6
MAX_EXAMPLES = 5
MAX_SUGGESTIONS = 3


@dataclass
class PhraseStats:
    key: str
    surfaces: Counter[str] = field(default_factory=Counter)
    # work_id -> weight (sum of part weights, capped at 1.0 when scored), all parts
    weights: dict[str, float] = field(default_factory=dict)
    # the same for title-type text only (own title and reference titles): the text that is
    # comparable with the background titles, so the scores are computed from it
    tweights: dict[str, float] = field(default_factory=dict)
    in_title: set[str] = field(default_factory=set)
    in_own: set[str] = field(default_factory=set)  # title, abstract or TLDR
    first_year: int | None = None
    merged_from: set[str] = field(default_factory=set)

    def add(self, work_id: str, weight: float, *, part: str, year: int | None, surface: str):
        self.surfaces[surface] += 1
        self.weights[work_id] = self.weights.get(work_id, 0.0) + weight
        if part in ("title", "refs"):
            self.tweights[work_id] = self.tweights.get(work_id, 0.0) + weight
        if part == "title":
            self.in_title.add(work_id)
        if part != "refs":
            self.in_own.add(work_id)
            if year is not None and (self.first_year is None or year < self.first_year):
                self.first_year = year

    def absorb(self, other: PhraseStats) -> None:
        self.surfaces.update(other.surfaces)
        for wid, w in other.weights.items():
            self.weights[wid] = max(self.weights.get(wid, 0.0), w) if wid in self.weights else w
        for wid, w in other.tweights.items():
            self.tweights[wid] = max(self.tweights.get(wid, 0.0), w) if wid in self.tweights else w
        self.in_title |= other.in_title
        self.in_own |= other.in_own
        years = [y for y in (self.first_year, other.first_year) if y is not None]
        self.first_year = min(years) if years else None
        self.merged_from |= {other.key} | other.merged_from

    @property
    def df(self) -> int:
        return len(self.weights)

    @property
    def wdf(self) -> float:
        """Weighted document frequency over title-type text (what the scores use)."""
        return sum(min(1.0, w) for w in self.tweights.values())

    @property
    def tdf(self) -> int:
        return len(self.tweights)

    @property
    def surface(self) -> str:
        # most frequent surface; ties: shorter, then alphabetical (deterministic)
        return sorted(self.surfaces.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0]


def _year(parts: CompositeParts) -> int | None:
    return int(parts.year) if parts.year else None


def count_phrases(parts: Sequence[CompositeParts], cfg: MineConfig) -> dict[str, PhraseStats]:
    """Phrase statistics over the FLAT works."""
    stats: dict[str, PhraseStats] = {}

    def add(p: CompositeParts, text: str, weight: float, part: str) -> None:
        for key, surface in extract(text, min_n=cfg.min_ngram, max_n=cfg.max_ngram).items():
            s = stats.setdefault(key, PhraseStats(key))
            s.add(p.work_id, weight, part=part, year=_year(p), surface=surface)

    for p in parts:
        add(p, p.title, cfg.title_weight, "title")
        if p.abstract:
            add(p, p.abstract, cfg.abstract_weight, "abstract")
        if p.tldr:
            add(p, p.tldr, cfg.tldr_weight, "tldr")
        # A phrase counts once per work from its references, however many titles hold it.
        ref_keys: dict[str, str] = {}
        for title in p.reference_titles:
            ref_keys.update(
                {
                    k: s
                    for k, s in extract(title, min_n=cfg.min_ngram, max_n=cfg.max_ngram).items()
                    if k not in ref_keys
                }
            )
        for key, surface in sorted(ref_keys.items()):
            s = stats.setdefault(key, PhraseStats(key))
            s.add(p.work_id, cfg.reference_weight, part="refs", year=None, surface=surface)
    return stats


def merge_generic_tails(stats: dict[str, PhraseStats]) -> dict[str, PhraseStats]:
    """Fold "X product" into "X" when both exist (the variant merge of 'shuffle product')."""
    out = dict(stats)
    for key in sorted(stats):
        tokens = key.split()
        if len(tokens) >= 2 and tokens[-1] in GENERIC_TAILS:
            head = " ".join(tokens[:-1])
            if head in out and key in out and head != key:
                out[head].absorb(out.pop(key))
    return out


def background_counts(titles: Sequence[str], cfg: MineConfig, bg: BackgroundConfig) -> Counter[str]:
    """Document frequency of each phrase key over the background titles."""
    excluded = [fold(w) for w in bg.exclude_title_words]
    counts: Counter[str] = Counter()
    for title in titles:
        folded = fold(title)
        if any(w in folded for w in excluded):
            continue
        counts.update(extract(title, min_n=cfg.min_ngram, max_n=cfg.max_ngram).keys())
    return counts


def ctfidf(
    stats: Mapping[str, PhraseStats], bg_counts: Mapping[str, int], n_flat: int, n_bg: int
) -> dict[str, float]:
    """c-TF-IDF of every phrase for the FLAT class against the background class.

    ``tf`` is the weighted document count in the FLAT works; ``f_t`` the count over both classes,
    the background scaled to the size of the FLAT class; ``A`` the mean total of the two classes.
    """
    scale = n_flat / max(n_bg, 1)
    total_flat = sum(s.wdf for s in stats.values())
    total_bg = sum(bg_counts.values()) * scale
    mean_class = (total_flat + total_bg) / 2
    scores = {}
    for key, s in stats.items():
        f_t = s.wdf + bg_counts.get(key, 0) * scale
        scores[key] = s.wdf * math.log(1 + mean_class / f_t) if f_t > 0 else 0.0
    return scores


def specificity(wdf: float, bg_df: int, n_flat: int, n_bg: int) -> float:
    """Share of the phrase's rate (per document) that belongs to the FLAT class, in [0, 1]."""
    p_flat = wdf / max(n_flat, 1)
    p_bg = bg_df / max(n_bg, 1)
    return (p_flat + 1e-9) / (p_flat + p_bg + 2e-9)


def ranking_score(wdf: float, spec: float) -> float:
    """Frequent AND specific: ``log(1 + wdf) * specificity^2``.

    Raw c-TF-IDF is kept as a column, but it grows linearly with frequency, so on its own it
    puts "automata" and "problems" above every precise phrase (checked on the pilot, D-81).
    """
    return math.log1p(wdf) * spec * spec


def prune_subphrases(keys: Sequence[str], df: Mapping[str, int], ratio: float = 0.8) -> set[str]:
    """Keys that are a contiguous part of a longer kept phrase with at least ``ratio`` of its df."""
    pool = set(keys)
    drop: set[str] = set()
    for key in sorted(keys, key=lambda k: (-len(k.split()), k)):
        if key in drop:
            continue
        tokens = key.split()
        for n in range(1, len(tokens)):
            for i in range(len(tokens) - n + 1):
                sub = " ".join(tokens[i : i + n])
                if sub in pool and sub != key and df[key] >= ratio * df[sub]:
                    drop.add(sub)
    return drop


def centroid_suggestions(
    keys: Sequence[str],
    stats: Mapping[str, PhraseStats],
    vectors: Mapping[str, np.ndarray],
    threshold: float,
    min_works: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """For each phrase, other phrases whose works' mean vector has cosine >= ``threshold``."""
    names, rows = [], []
    for key in keys:
        vecs = [vectors[w] for w in sorted(stats[key].in_own) if w in vectors]
        if len(vecs) >= min_works:
            names.append(key)
            rows.append(np.mean(vecs, axis=0))
    if len(rows) < 2:
        return {}
    matrix = np.vstack(rows)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    cosine = matrix @ matrix.T
    out: dict[str, list[dict[str, Any]]] = {}
    for i, key in enumerate(names):
        hits = []
        for j in np.argsort(-cosine[i], kind="stable"):
            other = names[j]
            if j == i or cosine[i, j] < threshold:
                continue
            if other in key or key in other:  # sub-phrases are handled by pruning
                continue
            hits.append({"phrase": stats[other].surface, "cosine": round(float(cosine[i, j]), 4)})
            if len(hits) == MAX_SUGGESTIONS:
                break
        if hits:
            out[key] = hits
    return out


def mine(
    parts: Sequence[CompositeParts],
    background_titles: Sequence[str],
    cfg: MineConfig,
    bg: BackgroundConfig,
    *,
    vectors: Mapping[str, np.ndarray] | None = None,
    keywords: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    """The candidate phrases, best first, as rows for ``phrases.parquet``."""
    stats = merge_generic_tails(count_phrases(parts, cfg))
    # Vocabulary comes from title-type text; abstracts and TLDRs only add evidence to it. Prose
    # words ("shown", "given") would otherwise outrank real terms against a titles-only background.
    # Phrases found only in reference titles (book names, authors, publishers) are not topics: the
    # work's own title, abstract or TLDR must hold the phrase too. ASCII only (no stray CJK titles).
    stats = {
        k: s
        for k, s in stats.items()
        if s.tdf >= cfg.min_docs and len(s.in_own) >= cfg.min_docs and k.isascii()
    }
    bg_counts = background_counts(background_titles, cfg, bg)
    n_bg = sum(
        1 for t in background_titles if not any(fold(w) in fold(t) for w in bg.exclude_title_words)
    )
    raw = ctfidf(stats, bg_counts, len(parts), n_bg)
    spec = {
        k: specificity(s.wdf, int(bg_counts.get(k, 0)), len(parts), n_bg) for k, s in stats.items()
    }
    scores = {k: ranking_score(stats[k].wdf, spec[k]) for k in stats}
    drop = prune_subphrases(list(stats), {k: s.df for k, s in stats.items()})
    ranked = sorted((k for k in stats if k not in drop), key=lambda k: (-scores[k], k))
    ranked = ranked[: cfg.top_candidates]

    suggestions = (
        centroid_suggestions(ranked, stats, vectors, cfg.merge_embedding_cosine) if vectors else {}
    )
    kw_by_key: dict[str, int] = defaultdict(int)
    for name, n in (keywords or {}).items():
        kw_by_key[key_of(name)] += n

    rows: list[dict[str, Any]] = []
    for rank, key in enumerate(ranked, 1):
        s = stats[key]
        examples = sorted(s.weights, key=lambda w: (w not in s.in_title, -s.weights[w], w))[
            :MAX_EXAMPLES
        ]
        rows.append(
            {
                "rank": rank,
                "phrase": s.surface,
                "key": key,
                "n_tokens": len(key.split()),
                "source": "text",
                "score": round(scores[key], 4),
                "ctfidf": round(raw[key], 4),
                "specificity": round(spec[key], 4),
                "df": s.df,
                "df_title": len(s.in_title),
                "df_own": len(s.in_own),
                "df_background": int(bg_counts.get(key, 0)),
                "weighted_df": round(s.wdf, 3),
                "first_year": s.first_year,
                "examples": examples,
                "variants": [v for v, _ in s.surfaces.most_common(MAX_VARIANTS)],
                "merged_from": sorted(s.merged_from),
                "merge_suggestions": suggestions.get(key, []),
                "openalex_keyword_works": kw_by_key.pop(key, None),
            }
        )
    # Keywords that matched no mined phrase: listed as candidates, apart, with their source.
    for key, n in sorted(kw_by_key.items(), key=lambda kv: (-kv[1], kv[0])):
        if n >= cfg.min_docs:
            rows.append(
                {
                    "rank": None,
                    "phrase": key,
                    "key": key,
                    "n_tokens": len(key.split()),
                    "source": "openalex_keyword",
                    "score": None,
                    "ctfidf": None,
                    "specificity": None,
                    "df": None,
                    "df_title": None,
                    "df_own": None,
                    "df_background": int(bg_counts.get(key, 0)),
                    "weighted_df": None,
                    "first_year": None,
                    "examples": [],
                    "variants": [],
                    "merged_from": [],
                    "merge_suggestions": [],
                    "openalex_keyword_works": n,
                }
            )
    return rows
