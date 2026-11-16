"""The readable review document of a proposal (``docs/notes/taxonomy-review-vN.md``).

Per topic: name, aliases, parents with their evidence, size, seeds, and five example works. The
outline follows the proposed parent links: a topic sits under its best parent and says where else
it belongs. The document holds no dates, so two runs of the same inputs give the same file.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from flatatlas.taxonomy.propose import Result
from flatatlas.taxonomy.schema import topic_levels
from flatatlas.text.composite import CompositeParts

EVIDENCE_NAMES = {
    "subsumption": "co-assignment",
    "seed-structure": "seed scheme",
    "head": "head word",
    "nested-clusters": "nested clusters",
    "citation": "citations",
}


def _work_line(work_id: str, info: Mapping[str, CompositeParts]) -> str:
    p = info.get(work_id)
    if p is None:
        return f"`{work_id}`"
    where = " ".join(x for x in (p.venue, p.year) if x)
    return f"{p.title} ({where}) `{work_id}`"


def _parent_text(topic, names: Mapping[str, str]) -> str:
    links = topic.evidence["parent_links"] if topic.evidence else []
    if not links:
        return "none (root)"
    parts = []
    for lk in links:
        name = names[lk["parent"]]
        if lk["soft"]:
            parts.append(
                f"{name} (soft: holds {lk['p_parent_given_child']:.0%} of this topic's works)"
            )
        else:
            ev = ", ".join(EVIDENCE_NAMES.get(k, k) for k in lk["evidence"])
            pc, cp = lk["p_parent_given_child"], lk["p_child_given_parent"]
            parts.append(
                f"{name} (score {lk['score']}: {ev}; P(parent|child) {pc:.2f}, "
                f"P(child|parent) {cp:.2f})"
            )
    return "; ".join(parts)


def render(
    result: Result, parts: Sequence[CompositeParts], *, version: int, config_hash: str
) -> str:
    info = {p.work_id: p for p in parts}
    topics = {t.id: t for t in result.file.topics}
    names = {t.id: t.name for t in result.file.topics}
    levels = topic_levels(result.file.topics)
    children: dict[str, list[str]] = defaultdict(list)
    for t in topics.values():
        if t.parents:
            children[t.parents[0]].append(t.id)
    size = {t.id: t.evidence["size"] for t in topics.values()}

    def order(ids: list[str]) -> list[str]:
        return sorted(ids, key=lambda i: (-size[i], i))

    s = result.stats
    out = [
        f"# Taxonomy proposal v{version}: review document",
        "",
        "Written by `flatatlas taxonomy propose` from the pilot corpus; the machine-readable",
        f"proposal is `taxonomy/proposals/v{version}.yaml`. Nothing here is decided: this is the",
        "raw material for the draft of `taxonomy/topics.yaml` (P1-06) and for your review.",
        "",
        "## Summary",
        "",
        f"- {s['topics']} candidate topics from {s['works']} works "
        f"({s['mined']} from mined phrases, {s['cluster']} from clusters no phrase covers).",
        f"- {s['roots']} roots (no parent). Levels: "
        + ", ".join(f"level {k}: {v}" for k, v in s["levels"].items())
        + ".",
        f"- Parents: {s['with_scored_parent']} topics have a parent backed by evidence, "
        f"{s['with_soft_parent']} a soft parent (containment only).",
        f"- {s['with_seed_match']} topics matched an MSC or CCS entry by name; "
        f"{s['unmatched_seeds']} seed entries matched no topic (listed below).",
        f"- Settings hash `{config_hash}` (`config/taxonomy.yaml`).",
        "- `taxonomy check` on the proposal: "
        + (
            "passes." if not result.problems else f"{len(result.problems)} problem(s), listed last."
        ),
        "",
        "**How to read an entry.** *size* is the number of works whose own title, abstract or TLDR",
        "holds one of the topic's phrases (or the cluster's size). *Parents* give the evidence:",
        "co-assignment (most works of the child are also in the parent, not the other way round),",
        "head word (the parent's phrase ends the child's), nested clusters, citations, seed",
        "scheme.",
        "A *soft* parent has only containment. Examples are the five most cited in-corpus works",
        "with the phrase in the title (clusters: the five closest to the cluster centre).",
        "",
        "## Seed entries no topic matched",
        "",
    ]
    if result.unmatched_seeds:
        out += [f"- {x['scheme'].upper()} {x['id']}: {x['label']}" for x in result.unmatched_seeds]
    else:
        out.append("(none)")
    out += ["", "## Topics", ""]

    def block(topic_id: str, depth: int) -> None:
        t = topics[topic_id]
        ev = t.evidence or {}
        pad = "  " * depth
        out.append(
            f"{pad}- **{t.name}** `{t.id}` · size {ev['size']} · {t.origin} · level "
            f"{levels.get(t.id, '?')}"
        )
        sub = pad + "  - "
        if t.aliases:
            out.append(f"{sub}aliases: {', '.join(t.aliases)}")
        out.append(f"{sub}parents: {_parent_text(t, names)}")
        if len(t.parents) > 1:
            out.append(f"{sub}also under: {', '.join(names[p] for p in t.parents[1:])}")
        seeds = ev.get("seeds") or []
        if seeds or ev.get("openalex_topics"):
            bits = [f"{m['scheme'].upper()} {m['id']} ({m['label']})" for m in seeds]
            bits += [
                f"OpenAlex {o['id']} {o['name']} ({o['share']:.0%})" for o in ev["openalex_topics"]
            ]
            out.append(f"{sub}seeds: {'; '.join(bits)}")
        if ev.get("clusters"):
            out.append(
                f"{sub}clusters: "
                + ", ".join(f"{c['cluster']} ({c['jaccard']:.2f})" for c in ev["clusters"])
            )
        for i, ex in enumerate(ev["examples"], 1):
            out.append(f"{sub}example {i}: {_work_line(ex['work'], info)}")
        for child in order(children.get(t.id, [])):
            block(child, depth + 1)

    roots = order([t.id for t in topics.values() if not t.parents])
    for root in roots:
        block(root, 0)
        out.append("")
    if result.problems:
        out += ["## Problems found by `taxonomy check`", ""]
        out += [f"- {p}" for p in result.problems]
    return "\n".join(out).rstrip() + "\n"
