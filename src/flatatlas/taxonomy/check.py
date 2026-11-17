"""``flatatlas taxonomy check``: the rules for ``topics.yaml``, proposals and ``gold.yaml``.

Every rule returns plain messages, so the command can report all problems at once and the tests
can break one rule at a time. Rule 6 of CLAUDE.md is enforced here: an entry with
``reviewed: true`` in git HEAD must be unchanged in the working copy unless the caller passes
``allow_reviewed_edits``.
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

import yaml
from pydantic import ValidationError

from flatatlas.settings import PROJECT_ROOT
from flatatlas.taxonomy.schema import (
    AnchorsFile,
    GoldFile,
    TopicEntry,
    TopicsFile,
    normalise_phrase,
    phrase_has_context,
    phrase_text,
    split_for,
    topic_levels,
)

TOPICS_FILE = PROJECT_ROOT / "taxonomy" / "topics.yaml"
GOLD_FILE = PROJECT_ROOT / "taxonomy" / "gold.yaml"
ANCHORS_FILE = PROJECT_ROOT / "taxonomy" / "anchors.yaml"
ALLOW_FLAG = "use --allow-reviewed-edits"
MAX_GOLD_LEVEL = 1  # labels are level 0 and level 1 only (PLAN §9.6)


class TaxonomyFileError(ValueError):
    """A file that cannot be read or does not fit its schema."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


# -- reading --------------------------------------------------------------------------------------


def _parse(text: str, origin: str) -> dict:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise TaxonomyFileError([f"{origin}: not valid YAML: {exc}"]) from None
    if not isinstance(data, dict):
        raise TaxonomyFileError([f"{origin}: expected a mapping at the top level"])
    return data


def _validation_problems(exc: ValidationError, origin: str) -> list[str]:
    out = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"])
        out.append(f"{origin}: {where}: {err['msg']}")
    return out


def parse_topics(text: str, origin: str = "topics") -> TopicsFile:
    data = _parse(text, origin)
    try:
        return TopicsFile.model_validate(data)
    except ValidationError as exc:
        raise TaxonomyFileError(_validation_problems(exc, origin)) from None


def parse_gold(text: str, origin: str = "gold") -> GoldFile:
    data = _parse(text, origin)
    try:
        return GoldFile.model_validate(data)
    except ValidationError as exc:
        raise TaxonomyFileError(_validation_problems(exc, origin)) from None


def parse_anchors(text: str, origin: str = "anchors") -> AnchorsFile:
    data = _parse(text, origin)
    try:
        return AnchorsFile.model_validate(data)
    except ValidationError as exc:
        raise TaxonomyFileError(_validation_problems(exc, origin)) from None


def load_anchors(path: Path = ANCHORS_FILE) -> AnchorsFile:
    return parse_anchors(path.read_text(encoding="utf-8"), path.name)


def load_topics(path: Path = TOPICS_FILE) -> TopicsFile:
    return parse_topics(path.read_text(encoding="utf-8"), path.name)


def load_gold(path: Path = GOLD_FILE) -> GoldFile:
    return parse_gold(path.read_text(encoding="utf-8"), path.name)


def git_head_text(path: Path, *, repo: Path = PROJECT_ROOT) -> str | None:
    """The content of ``path`` at git HEAD, or None (not a repository, or not tracked)."""
    try:
        rel = path.resolve().relative_to(repo.resolve())
    except ValueError:
        return None
    try:
        done = subprocess.run(  # noqa: S603 - fixed argument list
            ["git", "-C", str(repo), "show", f"HEAD:{rel.as_posix()}"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


# -- topics ---------------------------------------------------------------------------------------


def _find_cycle(topics: list[TopicEntry]) -> list[str] | None:
    """One cycle of the parent graph as a list of ids (first id repeated at the end), or None."""
    by_id = {t.id: t for t in topics}
    done: set[str] = set()

    def visit(node: str, trail: list[str]) -> list[str] | None:
        if node in trail:
            return [*trail[trail.index(node) :], node]
        if node in done:
            return None
        for parent in by_id[node].parents:
            if parent in by_id:
                found = visit(parent, [*trail, node])
                if found:
                    return found
        done.add(node)
        return None

    for topic in sorted(by_id):
        found = visit(topic, [])
        if found:
            return found
    return None


def check_topics(
    file: TopicsFile,
    *,
    head: TopicsFile | None = None,
    allow_reviewed_edits: bool = False,
) -> list[str]:
    """All problems of a topics file (or proposal) as messages; empty means the file is valid."""
    problems: list[str] = []
    topics = file.topics
    by_id: dict[str, TopicEntry] = {}
    for t in topics:
        if t.id in by_id:
            problems.append(f"duplicate topic id: {t.id}")
        by_id[t.id] = t

    # Aliases: unique across topics, and not another topic's id or name.
    owner: dict[str, str] = {}
    for t in topics:
        own_keys = {normalise_phrase(t.name), normalise_phrase(t.id)}
        for alias in t.aliases:
            key = normalise_phrase(alias)
            if not key:
                problems.append(f"{t.id}: empty alias")
            elif key in owner and owner[key] != t.id:
                problems.append(f"alias {alias!r} is used by both {owner[key]} and {t.id}")
            elif key not in own_keys:
                owner[key] = t.id
    names = {normalise_phrase(t.name): t.id for t in topics}
    for t in topics:
        for alias in t.aliases:
            other = names.get(normalise_phrase(alias))
            if other is not None and other != t.id:
                problems.append(f"alias {alias!r} of {t.id} is the name of topic {other}")

    # Parents exist.
    for t in topics:
        for parent in t.parents:
            if parent not in by_id:
                problems.append(f"{t.id}: parent {parent!r} does not exist")
            elif by_id[parent].status == "deprecated" and t.status != "deprecated":
                problems.append(f"{t.id}: parent {parent!r} is deprecated")

    cycle = _find_cycle(topics)
    if cycle:
        problems.append("cycle in the topic graph: " + " -> ".join(cycle))

    # Every topic that is not a root must reach a root through its parents.
    if cycle is None:
        levels = topic_levels(topics)
        for t in topics:
            if t.id not in levels and all(p in by_id for p in t.parents):
                problems.append(f"{t.id}: does not reach a root topic")

    # Phrases.
    for t in topics:
        include = {normalise_phrase(phrase_text(p)) for p in t.include_phrases} | {
            normalise_phrase(a) for a in t.aliases
        }
        for p in t.exclude_phrases:
            if normalise_phrase(phrase_text(p)) in include:
                problems.append(f"{t.id}: {phrase_text(p)!r} is both included and excluded")
        for p in (*t.include_phrases, *t.exclude_phrases):
            if not normalise_phrase(phrase_text(p)):
                problems.append(f"{t.id}: empty phrase")
    problems.extend(_sibling_phrase_problems(topics))

    problems.extend(_reviewed_problems(file, head, allow_reviewed_edits))
    return problems


def _sibling_phrase_problems(topics: list[TopicEntry]) -> list[str]:
    """Siblings (topics with a parent in common, or two roots) must not share a phrase unless every
    occurrence carries a context word."""
    groups: dict[str, list[TopicEntry]] = defaultdict(list)
    for t in topics:
        for parent in t.parents or ["<root>"]:
            groups[parent].append(t)
    out: set[str] = set()
    for parent, members in groups.items():
        seen: dict[str, list[tuple[str, bool]]] = defaultdict(list)
        for t in members:
            for p in t.include_phrases:
                seen[normalise_phrase(phrase_text(p))].append((t.id, phrase_has_context(p)))
            for alias in t.aliases:
                seen[normalise_phrase(alias)].append((t.id, False))
        for phrase, uses in sorted(seen.items()):
            ids = sorted({i for i, _ in uses})
            if len(ids) > 1 and not all(ctx for _, ctx in uses):
                where = "roots" if parent == "<root>" else f"children of {parent}"
                shared = ", ".join(ids)
                out.add(f"phrase {phrase!r} is shared by {shared} ({where}) without context")
    return sorted(out)


def _reviewed_problems(
    file: TopicsFile, head: TopicsFile | None, allow_reviewed_edits: bool
) -> list[str]:
    if head is None or allow_reviewed_edits:
        return []
    now = file.by_id()
    out = []
    for old in head.topics:
        if not old.reviewed:
            continue
        new = now.get(old.id)
        if new is None:
            out.append(f"{old.id}: reviewed topic was removed (use --allow-reviewed-edits)")
        elif new.model_dump() != old.model_dump():
            changed = sorted(k for k, v in old.model_dump().items() if new.model_dump().get(k) != v)
            out.append(
                f"{old.id}: reviewed topic changed ({', '.join(changed)}); "
                "use --allow-reviewed-edits"
            )
    return out


# -- anchors and venue expectations ---------------------------------------------------------------


def check_anchors(
    anchors: AnchorsFile,
    topics: TopicsFile,
    *,
    head: AnchorsFile | None = None,
    allow_reviewed_edits: bool = False,
) -> list[str]:
    """Offline rules for ``anchors.yaml``; whether the identifiers exist is checked by
    ``flatatlas taxonomy anchors``, which needs the sources."""
    problems: list[str] = []
    known = topics.by_id()
    if anchors.taxonomy_version != topics.taxonomy_version:
        problems.append(
            f"anchors: taxonomy_version is {anchors.taxonomy_version} but topics.yaml has "
            f"{topics.taxonomy_version}"
        )
    seen: dict[str, str] = {}
    for a in anchors.anchors:
        if a.id in seen:
            problems.append(f"anchor {a.id}: listed twice")
        seen[a.id] = a.id
        if a.doi is None and a.dblp is None:
            problems.append(f"anchor {a.id}: needs a doi or a dblp key")
        if a.topic not in known:
            problems.append(f"anchor {a.id}: topic {a.topic!r} is not a topic")
        elif known[a.topic].status == "deprecated":
            problems.append(f"anchor {a.id}: topic {a.topic!r} is deprecated")
    for field in ("doi", "dblp"):
        owners: dict[str, list[str]] = defaultdict(list)
        for a in anchors.anchors:
            value = getattr(a, field)
            if value:
                owners[value].append(a.id)
        for value, ids in sorted(owners.items()):
            if len(ids) > 1:
                problems.append(f"{field} {value} is used by several anchors: {', '.join(ids)}")
    if head is not None and not allow_reviewed_edits:
        now = {a.id: a for a in anchors.anchors}
        for old in head.anchors:
            if not old.reviewed:
                continue
            new = now.get(old.id)
            if new is None:
                problems.append(f"anchor {old.id}: reviewed anchor removed ({ALLOW_FLAG})")
            elif new.model_dump() != old.model_dump():
                problems.append(f"anchor {old.id}: reviewed anchor changed ({ALLOW_FLAG})")
    return problems


def check_expected_topics(expected: dict[str, list[str]], topics: TopicsFile) -> list[str]:
    """``expected_topics`` of each venue in ``config/venues.yaml`` must name active topics."""
    known = topics.by_id()
    problems = []
    for venue, ids in sorted(expected.items()):
        for topic in ids:
            if topic not in known:
                problems.append(f"venue {venue}: expected topic {topic!r} is not a topic")
            elif known[topic].status != "active":
                problems.append(f"venue {venue}: expected topic {topic!r} is {known[topic].status}")
    return problems


# -- labelled set ---------------------------------------------------------------------------------


def check_gold(
    gold: GoldFile,
    topics: TopicsFile,
    *,
    resolve_work: Callable[[str], str | None],
    head: GoldFile | None = None,
    allow_reviewed_edits: bool = False,
) -> list[str]:
    """Rules of PLAN §9.6 for ``gold.yaml``.

    ``resolve_work`` returns the surviving Atlas ID of a work ID (following merges) or None when
    the ID is unknown; a label file must name surviving IDs.
    """
    problems: list[str] = []
    levels = topic_levels(topics.topics)
    known = topics.by_id()

    if gold.taxonomy_version != topics.taxonomy_version:
        problems.append(
            f"taxonomy_version is {gold.taxonomy_version} but topics.yaml has "
            f"{topics.taxonomy_version}; migrate the labels of merged or split topics"
        )

    seen: set[str] = set()
    for w in gold.works:
        if w.work in seen:
            problems.append(f"{w.work}: listed twice")
        seen.add(w.work)
        survivor = resolve_work(w.work)
        if survivor is None:
            problems.append(f"{w.work}: not a known work ID")
        elif survivor != w.work:
            problems.append(f"{w.work}: was merged into {survivor}; use that ID")
        for label in w.labels:
            if label not in known:
                problems.append(f"{w.work}: label {label!r} is not a topic")
            elif known[label].status == "deprecated":
                problems.append(f"{w.work}: label {label!r} is a deprecated topic")
            elif levels.get(label, MAX_GOLD_LEVEL + 1) > MAX_GOLD_LEVEL:
                problems.append(f"{w.work}: label {label!r} is deeper than level {MAX_GOLD_LEVEL}")
        if len(set(w.labels)) != len(w.labels):
            problems.append(f"{w.work}: duplicate label")
        expected = split_for(w.work)
        if w.split != expected:
            problems.append(f"{w.work}: split is {w.split!r} but the hash rule gives {expected!r}")
        if w.sampling == "topup" and w.split == "heldout":
            problems.append(f"{w.work}: a top-up work cannot be held out")

    if head is not None and not allow_reviewed_edits:
        now = {w.work: w for w in gold.works}
        for old in head.works:
            if not old.reviewed:
                continue
            new = now.get(old.work)
            if new is None:
                problems.append(f"{old.work}: reviewed label removed (use --allow-reviewed-edits)")
            elif new.model_dump() != old.model_dump():
                problems.append(f"{old.work}: reviewed label changed; use --allow-reviewed-edits")
    return problems
