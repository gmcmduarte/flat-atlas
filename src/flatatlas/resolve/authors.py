"""Authors (PLAN §8.3): DBLP PIDs are the anchor, other sources are mapped onto them.

DBLP's own disambiguation is trusted and two PIDs are never merged. For OpenAlex the stage first
*aligns* the author list of a paper with the DBLP list (by position when the lists agree, by name
otherwise), which also gives each DBLP author the affiliation OpenAlex holds. An OpenAlex author
ID is then linked to a PID when at least ``min_papers`` papers agree and at least ``min_share`` of
its aligned papers point to that PID; one paper is enough when the ORCIDs match. Anything else
stays unlinked and is listed in the report. Semantic Scholar author IDs are not harvested yet
(D-68 leaves them out of the stored fields), so ``s2_ids`` is empty.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from flatatlas.resolve.config import AuthorsConfig
from flatatlas.resolve.text import clean_person_name, name_similarity

Row = Mapping[str, Any]


@dataclass(frozen=True)
class ExternalAuthor:
    """One author of a paper as another source lists them (rows of one position merged)."""

    position: int
    author_id: str | None
    names: tuple[str, ...]
    orcid: str | None = None
    institutions: tuple[Row, ...] = ()  # rows with institution_id, institution_name, ror, ...
    raw_affiliations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Alignment:
    """One DBLP author of a paper and the external author taken to be the same person."""

    dblp_position: int
    pid: str
    external: ExternalAuthor | None
    score: float
    method: str  # position | name | none


def group_external_authors(rows: Iterable[Row], *, position_base: int = 0) -> list[ExternalAuthor]:
    """Merge the rows of one paper (one row per author and institution) into authors.

    ``position_base`` is the number the source uses for its first author (OpenAlex: 0); the
    result is numbered from 1 like DBLP.
    """
    by_pos: dict[int, list[Row]] = defaultdict(list)
    for row in rows:
        by_pos[int(row["position"]) - position_base + 1].append(row)
    result = []
    for position in sorted(by_pos):
        group = by_pos[position]
        names = tuple(
            dict.fromkeys(
                n
                for row in group
                for n in (row.get("author_name"), row.get("raw_author_name"))
                if n
            )
        )
        institutions = tuple(r for r in group if r.get("institution_id") or r.get("ror"))
        raw_aff = tuple(
            dict.fromkeys(r["raw_affiliation"] for r in group if r.get("raw_affiliation"))
        )
        result.append(
            ExternalAuthor(
                position=position,
                author_id=group[0].get("author_id"),
                names=names,
                orcid=next((r["orcid"] for r in group if r.get("orcid")), None),
                institutions=institutions,
                raw_affiliations=raw_aff,
            )
        )
    return result


def _best_name_score(dblp_name: str, ext: ExternalAuthor) -> float:
    return max((name_similarity(dblp_name, n) for n in ext.names), default=0.0)


def align_authors(
    dblp: Sequence[Row], external: Sequence[ExternalAuthor], cfg: AuthorsConfig
) -> list[Alignment]:
    """Align the DBLP author list of one paper with an external one.

    Equal lengths whose names all agree in order are aligned by position. Otherwise the best
    name matches are taken one-to-one (best first, ties by closeness of position); authors left
    over stay unaligned (``external=None``).
    """
    dblp = sorted(dblp, key=lambda r: r["position"])
    scores = [[_best_name_score(d["name_raw"], e) for e in external] for d in dblp]
    if len(dblp) == len(external) and all(
        scores[i][i] >= cfg.name_match_min for i in range(len(dblp))
    ):
        return [
            Alignment(d["position"], d["pid"], external[i], scores[i][i], "position")
            for i, d in enumerate(dblp)
        ]
    triples = sorted(
        (-scores[i][j], abs(i - j), i, j)
        for i in range(len(dblp))
        for j in range(len(external))
        if scores[i][j] >= cfg.name_match_min
    )
    used_d: set[int] = set()
    used_e: set[int] = set()
    taken: dict[int, tuple[int, float]] = {}
    for neg, _dist, i, j in triples:
        if i in used_d or j in used_e:
            continue
        used_d.add(i)
        used_e.add(j)
        taken[i] = (j, -neg)
    result = []
    for i, d in enumerate(dblp):
        if i in taken:
            j, score = taken[i]
            result.append(Alignment(d["position"], d["pid"], external[j], score, "name"))
        else:
            result.append(Alignment(d["position"], d["pid"], None, 0.0, "none"))
    return result


# -- mapping external IDs onto PIDs -------------------------------------------------------------


@dataclass(frozen=True)
class AuthorLink:
    external_id: str
    pid: str
    papers_agree: int
    papers_total: int
    share: float
    method: str  # shared-papers | orcid
    competing: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class UnlinkedAuthor:
    external_id: str
    reason: str
    papers_total: int
    pids: Mapping[str, int]


def map_external_authors(
    evidence: Iterable[tuple[str, str, str, bool]], cfg: AuthorsConfig
) -> tuple[dict[str, AuthorLink], list[UnlinkedAuthor]]:
    """Link external author IDs to PIDs.

    ``evidence`` has one tuple ``(paper, external_id, pid, orcid_agrees)`` per aligned author of
    each paper. A paper counts once per ID and PID.
    """
    papers: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    orcid_papers: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for paper, ext_id, pid, orcid_ok in evidence:
        papers[ext_id][pid].add(paper)
        if orcid_ok:
            orcid_papers[ext_id][pid].add(paper)
    links: dict[str, AuthorLink] = {}
    unlinked: list[UnlinkedAuthor] = []
    for ext_id in sorted(papers):
        counts = Counter({pid: len(p) for pid, p in papers[ext_id].items()})
        total = sum(counts.values())
        # Highest count first, PID as the tie-break, so the outcome never depends on input order.
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        best_pid, best_n = ranked[0]
        share = best_n / total
        competing = {pid: n for pid, n in ranked if pid != best_pid}
        if best_n >= cfg.min_papers and share >= cfg.min_share:
            links[ext_id] = AuthorLink(
                ext_id, best_pid, best_n, total, share, "shared-papers", competing
            )
            continue
        confirmed = [
            pid for pid, p in orcid_papers[ext_id].items() if len(p) >= cfg.orcid_min_papers
        ]
        if len(confirmed) == 1:
            pid = confirmed[0]
            links[ext_id] = AuthorLink(
                ext_id,
                pid,
                counts[pid],
                total,
                counts[pid] / total,
                "orcid",
                {p: n for p, n in counts.items() if p != pid},
            )
            continue
        if len(counts) > 1 and share < cfg.min_share:
            reason = "papers point to different PIDs"
        else:
            reason = f"only {best_n} paper(s) agree (needs {cfg.min_papers} or a matching ORCID)"
        unlinked.append(UnlinkedAuthor(ext_id, reason, total, dict(counts)))
    return links, unlinked


# -- core_author rows ---------------------------------------------------------------------------


def display_name(dblp_name: str) -> str:
    return clean_person_name(dblp_name)


def build_author_rows(
    dblp_authors: Iterable[Row],
    links: Mapping[str, AuthorLink],
    mint: Callable[[str], str],
    *,
    raw_names: Mapping[str, Iterable[str]] | None = None,
) -> list[dict[str, Any]]:
    """``core_author`` rows, one per DBLP PID, sorted by author ID."""
    by_pid: dict[str, list[str]] = defaultdict(list)
    for ext_id, link in links.items():
        by_pid[link.pid].append(ext_id)
    rows = []
    for author in dblp_authors:
        pid = author["pid"]
        variants = {display_name(author["name"])}
        variants.update(clean_person_name(v) for v in (author.get("name_variants") or []))
        variants.update(clean_person_name(v) for v in (raw_names or {}).get(pid, ()))
        display = display_name(author["name"])
        rows.append(
            {
                "author_id": mint(pid),
                "display_name": display,
                "name_variants": sorted(variants - {display}),
                "dblp_pid": pid,
                "orcid": author.get("orcid") or None,
                "openalex_ids": sorted(by_pid.get(pid, [])),
                "s2_ids": [],
                "resolution_confidence": 1.0,
                "resolution_method": "dblp-pid",
            }
        )
    rows.sort(key=lambda r: r["author_id"])
    return rows


def institution_of(ext: ExternalAuthor | None) -> dict[str, Any] | None:
    """The first institution OpenAlex lists for an author: ``{id, name, country}`` or ``None``.

    The ID is the ROR where there is one (PLAN §4.2), else the OpenAlex institution ID, each with
    a prefix so the two namespaces cannot collide.
    """
    if ext is None or not ext.institutions:
        return None
    row = ext.institutions[0]
    if row.get("ror"):
        inst_id = f"ror:{row['ror']}"
    elif row.get("institution_id"):
        inst_id = f"openalex:{row['institution_id']}"
    else:
        return None
    return {
        "id": inst_id,
        "name": row.get("institution_name"),
        "country": row.get("country_code"),
    }
