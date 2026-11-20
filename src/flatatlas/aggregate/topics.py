"""Per-topic aggregates (PLAN §4.5): by year, author, venue and work (D-102).

Every function reads ``m`` (works x topics, rolled up, ``membership.roll_up``) and the class of
each work. Rules for the work classes:

* volume (``sum of m``) counts ``tagged`` and ``low_confidence`` works, the latter at their own
  low confidence; ``untagged`` works have ``m = 0`` and never appear;
* hard counts (``papers``, ``n_works``) count only ``tagged`` works with ``m >= present_min``;
  ``low_confidence`` works are counted apart (``n_low_confidence``);
* a paper list ranks ``tagged`` works first, ``low_confidence`` works after them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyarrow as pa

from flatatlas.aggregate.membership import LOW_CONFIDENCE, TAGGED

_S = pa.string()

SCHEMAS: dict[str, pa.Schema] = {
    "agg_topic_year": pa.schema(
        [
            ("topic_id", _S),
            ("year", pa.int16()),
            ("papers", pa.int32()),
            ("volume", pa.float32()),
            ("citations", pa.int64()),
            ("n_low_confidence", pa.int32()),
        ]
    ),
    "agg_topic_author": pa.schema(
        [
            ("topic_id", _S),
            ("author_id", _S),
            ("score", pa.float32()),
            ("n_works", pa.int32()),
            ("first_year", pa.int16()),
            ("last_year", pa.int16()),
        ]
    ),
    "agg_topic_venue": pa.schema(
        [
            ("topic_id", _S),
            ("venue_id", _S),
            ("papers", pa.int32()),
            ("volume", pa.float32()),
            ("first_year", pa.int16()),
            ("last_year", pa.int16()),
        ]
    ),
    "agg_topic_work": pa.schema(
        [
            ("topic_id", _S),
            ("work_id", _S),
            ("confidence", pa.float32()),
            ("score", pa.float32()),
            ("rank", pa.int32()),
            ("low_confidence", pa.bool_()),
        ]
    ),
}


@dataclass(frozen=True)
class WorkTable:
    """What the aggregates need to know about each work, in the row order of ``m``."""

    work_ids: list[str]
    years: np.ndarray  # int, year of the earliest version
    cited_by: np.ndarray  # int, cited_by_count (0 when unknown)
    venue_idx: np.ndarray  # int index into ``venue_ids``; -1 when unknown
    venue_ids: list[str]
    classes: list[str]  # membership.TAGGED / LOW_CONFIDENCE / UNTAGGED
    authorship: tuple[np.ndarray, np.ndarray]  # (work index, author index), each pair once
    author_ids: list[str]

    def mask(self, cls: str) -> np.ndarray:
        return np.array([c == cls for c in self.classes], dtype=bool)


def _table(rows: dict[str, list], name: str) -> pa.Table:
    return pa.Table.from_pydict(rows, schema=SCHEMAS[name])


def summary(m: np.ndarray, works: WorkTable, present_min: float) -> dict[str, np.ndarray]:
    """Per topic: ``volume`` (sum of m), ``paper_count`` (tagged works present) and
    ``n_low_confidence`` (low-confidence works with any membership)."""
    tagged = works.mask(TAGGED)
    low = works.mask(LOW_CONFIDENCE)
    return {
        "volume": m.sum(axis=0, dtype=np.float64),
        "paper_count": ((m >= present_min) & tagged[:, None]).sum(axis=0),
        "n_low_confidence": ((m > 0) & low[:, None]).sum(axis=0),
    }


def topic_year(
    m: np.ndarray, works: WorkTable, topic_ids: list[str], present_min: float
) -> pa.Table:
    tagged = works.mask(TAGGED)
    low = works.mask(LOW_CONFIDENCE)
    rows: dict[str, list] = {k: [] for k in SCHEMAS["agg_topic_year"].names}
    for t, topic in enumerate(topic_ids):
        col = m[:, t]
        any_ = col > 0
        for year in np.unique(works.years[any_]):
            in_year = any_ & (works.years == year)
            counted = in_year & tagged & (col >= present_min)
            rows["topic_id"].append(topic)
            rows["year"].append(int(year))
            rows["papers"].append(int(counted.sum()))
            rows["volume"].append(float(col[in_year].sum()))
            rows["citations"].append(int(works.cited_by[counted].sum()))
            rows["n_low_confidence"].append(int((in_year & low).sum()))
    return _table(rows, "agg_topic_year")


def topic_author(
    m: np.ndarray, works: WorkTable, topic_ids: list[str], present_min: float
) -> pa.Table:
    work_idx, author_idx = works.authorship
    tagged = works.mask(TAGGED)
    rows: dict[str, list] = {k: [] for k in SCHEMAS["agg_topic_author"].names}
    n_authors = len(works.author_ids)
    for t, topic in enumerate(topic_ids):
        col = m[work_idx, t]
        sel = col > 0
        if not sel.any():
            continue
        a = author_idx[sel]
        w = work_idx[sel]
        score = np.bincount(a, weights=col[sel], minlength=n_authors)
        counted = tagged[w] & (col[sel] >= present_min)
        n_works = np.bincount(a[counted], minlength=n_authors)
        first = np.full(n_authors, np.iinfo(np.int32).max)
        last = np.full(n_authors, np.iinfo(np.int32).min)
        np.minimum.at(first, a, works.years[w])
        np.maximum.at(last, a, works.years[w])
        for au in np.unique(a):
            rows["topic_id"].append(topic)
            rows["author_id"].append(works.author_ids[au])
            rows["score"].append(float(score[au]))
            rows["n_works"].append(int(n_works[au]))
            rows["first_year"].append(int(first[au]))
            rows["last_year"].append(int(last[au]))
    return _table(rows, "agg_topic_author")


def topic_venue(
    m: np.ndarray, works: WorkTable, topic_ids: list[str], present_min: float
) -> pa.Table:
    tagged = works.mask(TAGGED)
    rows: dict[str, list] = {k: [] for k in SCHEMAS["agg_topic_venue"].names}
    for t, topic in enumerate(topic_ids):
        col = m[:, t]
        for v, venue in enumerate(works.venue_ids):
            in_v = (works.venue_idx == v) & (col > 0)
            if not in_v.any():
                continue
            counted = in_v & tagged & (col >= present_min)
            rows["topic_id"].append(topic)
            rows["venue_id"].append(venue)
            rows["papers"].append(int(counted.sum()))
            rows["volume"].append(float(col[in_v].sum()))
            rows["first_year"].append(int(works.years[in_v].min()))
            rows["last_year"].append(int(works.years[in_v].max()))
    return _table(rows, "agg_topic_venue")


def topic_work(m: np.ndarray, works: WorkTable, topic_ids: list[str]) -> pa.Table:
    """Paper ranking per topic: ``score = m * log(1 + cited_by_count)``.

    Tagged works come first, then low-confidence works; inside a class by score, then confidence,
    then work ID (so the order is the same on every run).
    """
    low = works.mask(LOW_CONFIDENCE)
    log_cites = np.log1p(works.cited_by.astype(np.float64))
    id_order = np.argsort(np.argsort(np.array(works.work_ids)))
    rows: dict[str, list] = {k: [] for k in SCHEMAS["agg_topic_work"].names}
    for t, topic in enumerate(topic_ids):
        col = m[:, t].astype(np.float64)
        idx = np.flatnonzero(col > 0)
        if len(idx) == 0:
            continue
        score = col[idx] * log_cites[idx]
        order = np.lexsort((id_order[idx], -col[idx], -score, low[idx].astype(int)))
        for rank, k in enumerate(order, start=1):
            w = idx[k]
            rows["topic_id"].append(topic)
            rows["work_id"].append(works.work_ids[w])
            rows["confidence"].append(float(col[w]))
            rows["score"].append(float(score[k]))
            rows["rank"].append(rank)
            rows["low_confidence"].append(bool(low[w]))
    return _table(rows, "agg_topic_work")
