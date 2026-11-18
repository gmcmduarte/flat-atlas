"""The labelled set (P1-06b, PLAN §9.6, D-61): sample, review sheets, finalise and report.

The sample is drawn at random with a fixed seed, stratified by venue, decade and has-abstract. It
reads only ``core_work``, ``core_version`` and ``core_venue``: never a tag, signal, phrase match or
cluster, so no tagger can steer which works are labelled. Every random choice is a hash of the
seed and the work ID, so the same frame and seed always give the same sample.

Three review files come from the sample:

- ``<data>/review/gold-blind.md``: the blind works, without labels, for Guilherme to label first.
  It holds abstracts and TLDRs, so it stays local (CLAUDE.md rule 2).
- ``taxonomy/proposals/gold-draft.yaml``: every sampled work in the ``gold.yaml`` format with
  Claude's draft labels and ``reviewed: false``. Committed, so it holds titles and links only.
- ``<data>/review/gold-context.md``: the composite text of the non-blind works, the drafting and
  look-up sheet. Local, like the blind file.

``finalise`` turns the reviewed draft and the blind labels into ``taxonomy/gold.yaml``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import duckdb
import yaml

from flatatlas.taxonomy.schema import (
    TOPIC_ID,
    GoldFile,
    GoldWork,
    TopicEntry,
    TopicsFile,
    split_for,
    topic_levels,
)
from flatatlas.text.composite import CompositeParts

SAMPLE_SALT = "gold-sample"
BLIND_SALT = "gold-blind"
ORDER_SALT = "gold-order"
MAX_LEVEL = 1


class GoldError(Exception):
    """A problem that stops a labelled-set step; ``problems`` lists every one found."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


# -- sampling -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FrameWork:
    """One in-scope work of the sampling frame."""

    work_id: str
    title: str
    venue: str
    year: int | None
    has_abstract: bool
    doi: str | None = None
    dblp_key: str | None = None

    @property
    def decade(self) -> str:
        return f"{(self.year // 10) * 10}s" if self.year else "unknown"

    @property
    def cell(self) -> str:
        """The stratum: venue, decade and has-abstract."""
        return f"{self.venue}|{self.decade}|{'abstract' if self.has_abstract else 'no-abstract'}"

    @property
    def links(self) -> list[str]:
        out = []
        if self.doi:
            out.append(f"https://doi.org/{self.doi}")
        if self.dblp_key:
            out.append(f"https://dblp.org/rec/{self.dblp_key}")
        return out


def sampling_frame(con: duckdb.DuckDBPyConnection) -> list[FrameWork]:
    """All in-scope works (``scope_status = 'core'``), ordered by work ID.

    Reads ``core_work``, its primary version and that version's venue, and nothing else.
    """
    rows = con.execute(
        """
        SELECT w.work_id, w.title, coalesce(v.acronym, 'unknown'), w.year,
               coalesce(w.has_abstract, false), pv.doi, pv.dblp_key
        FROM core_work w
        LEFT JOIN core_version pv ON pv.version_id = w.primary_version_id
        LEFT JOIN core_venue v ON v.venue_id = pv.venue_id
        WHERE w.scope_status = 'core'
        ORDER BY w.work_id
        """
    ).fetchall()
    return [
        FrameWork(
            work_id=r[0],
            title=r[1] or "",
            venue=r[2],
            year=int(r[3]) if r[3] is not None else None,
            has_abstract=bool(r[4]),
            doi=r[5],
            dblp_key=r[6],
        )
        for r in rows
    ]


def allocate(sizes: Mapping[str, int], n: int, min_per_cell: int) -> dict[str, int]:
    """Proportional allocation of ``n`` over the cells, with a floor of ``min_per_cell``.

    Each non-empty cell first gets ``max(min(min_per_cell, size), floor(quota))``; the total is then
    brought to exactly ``n`` by the largest remainder (adding to cells below their quota first,
    removing from cells furthest above it), never above a cell's size or below its floor. Ties go
    by cell key, so the result is deterministic.
    """
    cells = {c: s for c, s in sizes.items() if s > 0}
    total = sum(cells.values())
    if n > total:
        raise GoldError([f"asked for {n} works but the frame has only {total}"])
    floor_of = {c: min(min_per_cell, s) for c, s in cells.items()}
    if sum(floor_of.values()) > n:
        raise GoldError(
            [f"the per-cell minimum needs {sum(floor_of.values())} works, more than {n}"]
        )
    quota = {c: n * s / total for c, s in cells.items()}
    alloc = {c: max(floor_of[c], math.floor(quota[c])) for c in cells}
    while sum(alloc.values()) < n:
        grow = [c for c in cells if alloc[c] < cells[c]]
        best = max(grow, key=lambda c: (quota[c] - alloc[c], _desc(c)))
        alloc[best] += 1
    while sum(alloc.values()) > n:
        shrink = [c for c in cells if alloc[c] > floor_of[c]]
        best = max(shrink, key=lambda c: (alloc[c] - quota[c], _desc(c)))
        alloc[best] -= 1
    return alloc


def _desc(cell: str) -> tuple[int, ...]:
    """Tie-break key: the alphabetically first cell wins a tie (``max`` picks it)."""
    return tuple(-ord(ch) for ch in cell)


def rank(salt: str, seed: int, work_id: str) -> str:
    """The random but repeatable position of a work in a draw."""
    return hashlib.sha256(f"{salt}:{seed}:{work_id}".encode()).hexdigest()


@dataclass(frozen=True)
class SampledWork:
    work_id: str
    cell: str
    blind: bool


@dataclass
class Sample:
    seed: int
    n: int
    min_per_cell: int
    frame_counts: dict[str, int]
    quotas: dict[str, int]
    works: list[SampledWork] = field(default_factory=list)

    def ids(self) -> list[str]:
        return [w.work_id for w in self.works]

    def blind_ids(self) -> set[str]:
        return {w.work_id for w in self.works if w.blind}


def draw(
    frame: Sequence[FrameWork], *, n: int, seed: int, min_per_cell: int, n_blind: int
) -> Sample:
    """The stratified random sample and its blind subset (both chosen by hash of the seed)."""
    by_cell: dict[str, list[FrameWork]] = defaultdict(list)
    for w in frame:
        by_cell[w.cell].append(w)
    sizes = {c: len(ws) for c, ws in sorted(by_cell.items())}
    quotas = allocate(sizes, n, min_per_cell)
    chosen: list[tuple[str, str]] = []
    for cell, k in sorted(quotas.items()):
        ordered = sorted(by_cell[cell], key=lambda w: rank(SAMPLE_SALT, seed, w.work_id))
        chosen.extend((w.work_id, cell) for w in ordered[:k])
    blind = choose_blind([wid for wid, _ in chosen], n_blind, seed)
    works = [SampledWork(wid, cell, wid in blind) for wid, cell in sorted(chosen)]
    return Sample(seed, n, min_per_cell, sizes, dict(sorted(quotas.items())), works)


def choose_blind(work_ids: Iterable[str], n_blind: int, seed: int) -> set[str]:
    ids = sorted(set(work_ids), key=lambda wid: rank(BLIND_SALT, seed, wid))
    if n_blind > len(ids):
        raise GoldError([f"asked for {n_blind} blind works but the sample has {len(ids)}"])
    return set(ids[:n_blind])


def review_order(sample: Sample) -> list[SampledWork]:
    """The order of the review files: non-blind works first, each group in a random fixed order."""
    return sorted(sample.works, key=lambda w: (w.blind, rank(ORDER_SALT, sample.seed, w.work_id)))


def dump_sample(sample: Sample) -> str:
    data = {
        "seed": sample.seed,
        "n": sample.n,
        "min_per_cell": sample.min_per_cell,
        "frame_counts": sample.frame_counts,
        "quotas": sample.quotas,
        "works": [{"work": w.work_id, "cell": w.cell, "blind": w.blind} for w in sample.works],
    }
    header = "# Generated by `flatatlas gold sample`; do not edit (CLAUDE.md rule 5).\n"
    return header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


def load_sample(text: str) -> Sample:
    data = yaml.safe_load(text)
    return Sample(
        seed=int(data["seed"]),
        n=int(data["n"]),
        min_per_cell=int(data["min_per_cell"]),
        frame_counts=dict(data["frame_counts"]),
        quotas=dict(data["quotas"]),
        works=[SampledWork(w["work"], w["cell"], bool(w["blind"])) for w in data["works"]],
    )


# -- review sheets --------------------------------------------------------------------------------


def _q(text: str) -> str:
    """A YAML double-quoted scalar (JSON strings are valid YAML)."""
    return json.dumps(text, ensure_ascii=False)


def _flow(labels: Sequence[str]) -> str:
    return "[" + ", ".join(labels) + "]"


def render_gold_yaml(
    gold: GoldFile, meta: Mapping[str, FrameWork] | None = None, *, header: str = ""
) -> str:
    """``gold.yaml`` text: one block per work, labels on one line, an optional comment with venue,
    year and links (taken from ``meta``). Parsed back by ``check.parse_gold``."""
    lines = [header.rstrip("\n")] if header else []
    lines += [f"taxonomy_version: {gold.taxonomy_version}", "works:"]
    for w in gold.works:
        lines.append(f"- work: {w.work}")
        m = meta.get(w.work) if meta else None
        if m is not None:
            where = " ".join(x for x in (m.venue, str(m.year or "")) if x)
            lines.append("  # " + " · ".join([where, *m.links]))
        lines.append(f"  title: {_q(w.title)}")
        lines.append(f"  labels: {_flow(w.labels)}")
        lines.append(f"  split: {w.split}")
        lines.append(f"  sampling: {w.sampling}")
        lines.append(f"  blind: {str(w.blind).lower()}")
        lines.append(f"  reviewed: {str(w.reviewed).lower()}")
        lines.append(f"  note: {_q(w.note)}")
    return "\n".join(lines) + "\n"


DRAFT_HEADER = """\
# Draft labels of the labelled set (P1-06b). Generated by `flatatlas gold sheet`, labels drafted
# by Claude. Review guide: docs/notes/gold-review-guide.md.
# Edit only `labels` and `note`. Leave `split`, `blind` and `reviewed`: `gold finalise` sets them.
# Blind works (blind: true, at the end) are labelled in data/review/gold-blind.md, not here.
"""


def build_draft(
    sample: Sample,
    frame: Mapping[str, FrameWork],
    *,
    taxonomy_version: int,
    existing: GoldFile | None = None,
) -> GoldFile:
    """The draft: every sampled work in review order, keeping labels and notes already drafted."""
    kept = {w.work: w for w in existing.works} if existing else {}
    works = []
    for s in review_order(sample):
        old = kept.get(s.work_id)
        works.append(
            GoldWork(
                work=s.work_id,
                title=frame[s.work_id].title,
                labels=list(old.labels) if old else [],
                split=split_for(s.work_id),
                sampling="random",
                blind=s.blind,
                reviewed=False,
                note=old.note if old else "",
            )
        )
    return GoldFile(taxonomy_version=taxonomy_version, works=works)


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _work_block(i: int, fw: FrameWork, parts: CompositeParts) -> list[str]:
    lines = [f"## {i}. {fw.work_id}", "", f"**{parts.title or fw.title}**", ""]
    where = " ".join(x for x in (fw.venue, str(fw.year or "")) if x)
    lines.append(" · ".join([where, *fw.links]))
    lines.append("")
    if parts.reference_titles:
        lines.append(
            f"References ({len(parts.reference_titles)} of {parts.n_references_with_title} "
            "with a title):"
        )
        lines += [f"- {t}" for t in parts.reference_titles]
    else:
        lines.append("References: none with a title")
    lines.append("")
    if parts.abstract:
        lines += [f"Abstract: {_one_line(parts.abstract)}", ""]
    if parts.tldr:
        lines += [f"TLDR: {_one_line(parts.tldr)}", ""]
    if not parts.abstract and not parts.tldr:
        lines += ["(no abstract, no TLDR)", ""]
    return lines


def topic_list(topics: TopicsFile) -> list[str]:
    """Level-0 topics, then level-1 topics under each parent, with their descriptions."""
    levels = topic_levels(topics.topics)
    roots = [t for t in topics.topics if levels.get(t.id) == 0]
    lines = ["## Topics", "", "### Level 0", ""]
    lines += [f"- `{t.id}`: {_one_line(t.description)}" for t in roots]
    lines += ["", "### Level 1, by parent", ""]
    for root in roots:
        kids = [t for t in topics.topics if levels.get(t.id) == 1 and root.id in t.parents]
        lines.append(f"**{root.id}**")
        lines.append("")
        for t in kids:
            also = [p for p in t.parents if p != root.id]
            extra = f" (also under {', '.join(also)})" if also else ""
            lines.append(f"- `{t.id}`{extra}: {_one_line(t.description)}")
        lines.append("")
    return lines


BLIND_INTRO = """\
# Blind labels (P1-06b)

Label these {n} works **before** opening `taxonomy/proposals/gold-draft.yaml`: they measure how
much the draft steers the review. For each work, write on its `labels:` line every level-0 and
level-1 topic id it is *about* (usually 1 to 3 at each level); a level-1 label needs its level-0
parent as well. Separate ids by commas or spaces. Use `note:` for doubts. The topic list is at the
end. `flatatlas gold finalise` reads this file; keep the `## n. W…` headings as they are.

This file holds abstracts: it stays under `data/` and is never committed.
"""


def render_blind_md(
    sample: Sample,
    frame: Mapping[str, FrameWork],
    parts: Mapping[str, CompositeParts],
    topics: TopicsFile,
) -> str:
    blind = [s for s in review_order(sample) if s.blind]
    lines = [BLIND_INTRO.format(n=len(blind))]
    for i, s in enumerate(blind, 1):
        lines += _work_block(i, frame[s.work_id], parts[s.work_id])
        lines += ["labels:", "note:", ""]
    lines += topic_list(topics)
    return "\n".join(lines).rstrip() + "\n"


def render_context_md(
    sample: Sample, frame: Mapping[str, FrameWork], parts: Mapping[str, CompositeParts]
) -> str:
    """The composite text of the non-blind works, in the order of the draft."""
    works = [s for s in review_order(sample) if not s.blind]
    lines = [
        "# Labelled set: composite text of the draft works (P1-06b)",
        "",
        "Same order as `taxonomy/proposals/gold-draft.yaml`. Local only (holds abstracts).",
        "",
    ]
    for i, s in enumerate(works, 1):
        lines += _work_block(i, frame[s.work_id], parts[s.work_id])
    return "\n".join(lines).rstrip() + "\n"


_HEADING = re.compile(r"^## (\d+)\. (W[0-9A-Z]+)\s*$")
_LABELS = re.compile(r"^labels:(.*)$")
_NOTE = re.compile(r"^note:(.*)$")
_ID = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")


@dataclass(frozen=True)
class BlindEntry:
    labels: list[str]
    note: str


def parse_blind_md(text: str) -> dict[str, BlindEntry]:
    """Labels and notes from ``gold-blind.md``.

    ``labels: a, b``, ``labels: [a, b]`` and ``labels: a b`` all work. A work's section ends at the
    next ``## `` heading; its last ``labels:`` and ``note:`` lines count.
    """
    out: dict[str, BlindEntry] = {}
    current: str | None = None
    labels: list[str] = []
    note = ""

    def close() -> None:
        if current is not None:
            out[current] = BlindEntry(labels, note)

    for raw in text.splitlines():
        line = raw.strip()
        head = _HEADING.match(line)
        if head or line.startswith("## "):
            close()
            current = head.group(2) if head else None
            labels, note = [], ""
            continue
        if current is None:
            continue
        if m := _LABELS.match(line):
            labels = [x.lower() for x in _ID.findall(m.group(1))]
        elif m := _NOTE.match(line):
            note = m.group(1).strip()
    close()
    return out


# -- finalise -------------------------------------------------------------------------------------


def label_problems(work: GoldWork, topics: TopicsFile) -> list[str]:
    """Problems of one work's labels against the topics (the rules of ``gold finalise``)."""
    problems = []
    known = topics.by_id()
    levels = topic_levels(topics.topics)
    for label in work.labels:
        if not TOPIC_ID.match(label) or label not in known:
            problems.append(f"{work.work}: label {label!r} is not a topic")
        elif known[label].status == "deprecated":
            problems.append(f"{work.work}: label {label!r} is a deprecated topic")
        elif levels.get(label, MAX_LEVEL + 1) > MAX_LEVEL:
            problems.append(f"{work.work}: label {label!r} is not a level-0 or level-1 topic")
    if len(set(work.labels)) != len(work.labels):
        problems.append(f"{work.work}: duplicate label")
    if problems:
        return problems
    if not any(levels[label] == 0 for label in work.labels):
        problems.append(f"{work.work}: no level-0 label")
    for label in work.labels:
        if levels[label] == 1 and not set(known[label].parents) & set(work.labels):
            parents = " or ".join(known[label].parents)
            problems.append(f"{work.work}: {label!r} needs its parent {parents} as a label")
    return problems


def finalise(
    draft: GoldFile,
    blind: Mapping[str, BlindEntry],
    topics: TopicsFile,
    *,
    existing: GoldFile | None = None,
) -> GoldFile:
    """The reviewed labelled set: Guilherme's labels, split by hash, ``reviewed: true``.

    Labels are taken as they are, in their order: the draft's (as he reviewed it) for ordinary
    works, the blind file's for blind works. Entries already ``reviewed: true`` in ``existing``
    (an earlier ``gold.yaml``) are kept unchanged. Raises ``GoldError`` listing every problem;
    nothing is fixed silently.
    """
    problems: list[str] = []
    done = {w.work: w for w in existing.works if w.reviewed} if existing else {}
    if existing is not None and existing.taxonomy_version != draft.taxonomy_version:
        problems.append("the draft and the existing gold.yaml have different taxonomy versions")
    out: list[GoldWork] = []
    seen: set[str] = set()
    for w in draft.works:
        if w.work in seen:
            problems.append(f"{w.work}: listed twice in the draft")
            continue
        seen.add(w.work)
        if w.work in done:
            out.append(done[w.work])
            continue
        if w.blind:
            entry = blind.get(w.work)
            if entry is None:
                problems.append(f"{w.work}: blind work missing from gold-blind.md")
                continue
            labels, note = list(entry.labels), entry.note
        else:
            labels, note = list(w.labels), w.note
        final = GoldWork(
            work=w.work,
            title=w.title,
            labels=labels,
            split=split_for(w.work),
            sampling=w.sampling,
            blind=w.blind,
            reviewed=True,
            note=note,
        )
        if w.sampling == "topup" and split_for(w.work) == "heldout":
            # The hash rule fixes the split, so a top-up work must be one the hash puts in train.
            problems.append(f"{w.work}: a top-up work falls in the held-out part by hash")
        problems += label_problems(final, topics)
        out.append(final)
    extra = set(blind) - {w.work for w in draft.works if w.blind}
    problems += [
        f"{wid}: in gold-blind.md but not a blind work of the draft" for wid in sorted(extra)
    ]
    # Reviewed entries of the existing file that the draft no longer lists are kept as they are.
    out += [w for wid, w in done.items() if wid not in seen]
    if problems:
        raise GoldError(problems)
    return GoldFile(taxonomy_version=draft.taxonomy_version, works=out)


# -- report ---------------------------------------------------------------------------------------


def _jaccard(a: set[str], b: set[str]) -> float:
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def _pr(pred: list[set[str]], gold: list[set[str]]) -> tuple[float, float, int, int, int]:
    tp = sum(len(p & g) for p, g in zip(pred, gold, strict=True))
    n_pred = sum(len(p) for p in pred)
    n_gold = sum(len(g) for g in gold)
    precision = tp / n_pred if n_pred else float("nan")
    recall = tp / n_gold if n_gold else float("nan")
    return precision, recall, tp, n_pred, n_gold


def _by_level(labels: Iterable[str], levels: Mapping[str, int], level: int) -> set[str]:
    return {x for x in labels if levels.get(x) == level}


def render_report(gold: GoldFile, draft: GoldFile, topics: TopicsFile, *, thin: int = 5) -> str:
    """``docs/notes/gold-v1-report.md``: counts, changes, blind agreement and thin topics.

    ``draft`` is Claude's draft as committed before the review (labels of the blind works included,
    drafted after the blind file was handed in).
    """
    levels = topic_levels(topics.topics)
    ids = [t.id for t in topics.topics if levels.get(t.id, 9) <= MAX_LEVEL]
    by_id: dict[str, TopicEntry] = topics.by_id()
    drafted = {w.work: w for w in draft.works}
    random_works = [w for w in gold.works if w.sampling == "random"]
    split_n = Counter(w.split for w in gold.works)
    lines = [
        "# Labelled set v1: report (P1-06b)",
        "",
        f"Works: {len(gold.works)} ({len(random_works)} random, "
        f"{len(gold.works) - len(random_works)} top-up); train {split_n['train']}, "
        f"held out {split_n['heldout']}; blind {sum(w.blind for w in gold.works)}.",
        "",
    ]

    # Labels per work.
    lines += ["## Labels per work", "", "| level | mean | min | max |", "|---|---|---|---|"]
    for level in (0, 1):
        counts = [len(_by_level(w.labels, levels, level)) for w in gold.works]
        if counts:
            lines.append(
                f"| {level} | {sum(counts) / len(counts):.2f} | {min(counts)} | {max(counts)} |"
            )
    lines.append("")

    # Counts per topic and split.
    per: dict[str, Counter] = defaultdict(Counter)
    for w in gold.works:
        for label in w.labels:
            per[label][w.split] += 1
    lines += ["## Works per topic", "", "| topic | level | train | held out |", "|---|---|---|---|"]
    for tid in ids:
        lines.append(f"| `{tid}` | {levels[tid]} | {per[tid]['train']} | {per[tid]['heldout']} |")
    lines.append("")

    # Changes from the draft (non-blind works that were drafted).
    lines += ["## Draft labels changed in review (non-blind works)", ""]
    lines += [
        "| level | draft labels | kept | removed | added | changed share |",
        "|---|---|---|---|---|---|",
    ]
    for level in (0, 1):
        kept = removed = added = n_draft = 0
        for w in gold.works:
            d = drafted.get(w.work)
            if w.blind or d is None:
                continue
            a = _by_level(d.labels, levels, level)
            b = _by_level(w.labels, levels, level)
            n_draft += len(a)
            kept += len(a & b)
            removed += len(a - b)
            added += len(b - a)
        share = (removed + added) / (n_draft + added) if n_draft + added else float("nan")
        lines.append(f"| {level} | {n_draft} | {kept} | {removed} | {added} | {share:.1%} |")
    unchanged = sum(
        1
        for w in gold.works
        if not w.blind and w.work in drafted and set(drafted[w.work].labels) == set(w.labels)
    )
    n_non_blind = sum(1 for w in gold.works if not w.blind and w.work in drafted)
    lines += [
        "",
        f"Works whose labels were left exactly as drafted: {unchanged} of {n_non_blind}.",
        "",
    ]

    # Blind agreement.
    blind = [w for w in gold.works if w.blind and w.work in drafted]
    lines += ["## Blind works: draft against Guilherme's blind labels", ""]
    if blind:
        jac = [_jaccard(set(drafted[w.work].labels), set(w.labels)) for w in blind]
        lines.append(
            f"{len(blind)} works. Jaccard per work: mean {sum(jac) / len(jac):.2f}, "
            f"{sum(j == 1.0 for j in jac)} identical, {sum(j == 0.0 for j in jac)} disjoint."
        )
        lines += [
            "",
            "| level | precision | recall | agreed | draft | blind |",
            "|---|---|---|---|---|---|",
        ]
        for level in (0, 1):
            p, r, tp, n_pred, n_gold = _pr(
                [_by_level(drafted[w.work].labels, levels, level) for w in blind],
                [_by_level(w.labels, levels, level) for w in blind],
            )
            lines.append(f"| {level} | {p:.2f} | {r:.2f} | {tp} | {n_pred} | {n_gold} |")
        lines += ["", "| work | Jaccard | draft | blind |", "|---|---|---|---|"]
        for w, j in sorted(zip(blind, jac, strict=True), key=lambda x: (x[1], x[0].work)):
            mine, his = ", ".join(drafted[w.work].labels), ", ".join(w.labels)
            lines.append(f"| {w.work} | {j:.2f} | {mine} | {his} |")
    else:
        lines.append("No blind work has a draft to compare.")
    lines.append("")

    # Thin level-1 topics.
    thin_ids = [t for t in ids if levels[t] == 1 and per[t]["train"] < thin]
    lines += [f"## Level-1 topics with fewer than {thin} training works", ""]
    lines += [
        f"- `{t}` ({by_id[t].name}): {per[t]['train']} train, {per[t]['heldout']} held out"
        for t in thin_ids
    ]
    small_roots = [t for t in ids if levels[t] == 0 and per[t]["heldout"] < thin]
    lines += ["", f"## Level-0 topics with fewer than {thin} held-out works", ""]
    lines += [
        f"- `{t}`: {per[t]['heldout']} held out, {per[t]['train']} train" for t in small_roots
    ]
    return "\n".join(lines).rstrip() + "\n"
