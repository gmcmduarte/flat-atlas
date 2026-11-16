"""Works, versions, authorships and everything that hangs on them (PLAN §4.2, §8).

``resolve_corpus`` is the whole stage as a pure function: ``Inputs`` and a registry in, rows out.
Order of work:

1. Venues and editions get Atlas IDs; every DBLP paper gets a version ID.
2. Each paper is joined to its OpenAlex, Semantic Scholar and Crossref records (``match``); a
   record that fails the §8.1 rules is dropped and counted.
3. DBLP authors become ``core_author`` rows; OpenAlex author lists are aligned with DBLP's, which
   gives affiliations and the mapping of OpenAlex author IDs onto PIDs (``authors``).
4. Versions are scored pairwise and grouped into works (``merge``); work IDs are minted from the
   earliest version and the others are merged into it in the registry.
5. Rows are assembled with the precedence rules of §8.1: DBLP for authors and venue, Crossref
   for pages and volume, OpenAlex for affiliations and open-access links.

Every automatic link keeps its method and confidence (CLAUDE.md rule 4).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from flatatlas.ids import IdRegistry, RegistryError
from flatatlas.resolve.authors import (
    Alignment,
    AuthorLink,
    ExternalAuthor,
    UnlinkedAuthor,
    align_authors,
    build_author_rows,
    group_external_authors,
    institution_of,
    map_external_authors,
)
from flatatlas.resolve.citations import build_citation_rows
from flatatlas.resolve.config import ResolveConfig
from flatatlas.resolve.inputs import Inputs
from flatatlas.resolve.match import (
    SourceMatch,
    match_crossref,
    match_openalex,
    match_s2,
)
from flatatlas.resolve.merge import (
    Grouping,
    PairScore,
    VersionRef,
    candidate_pairs,
    group_versions,
    primary_version,
    score_pair,
)
from flatatlas.resolve.text import normalise_doi, page_count
from flatatlas.resolve.venues import build_edition_rows, build_venue_rows
from flatatlas.venues import VenueFacts, VenueRegistry

Row = dict[str, Any]

WORK_TYPE = {"proceedings": "proceedings-paper", "journal": "article", "preprint": "other"}
KIND_OF_VENUE = {"conference": "proceedings", "journal": "journal", "book-series": "proceedings"}


class ResolveError(RuntimeError):
    """The inputs or the registry are inconsistent; nothing is written."""


@dataclass
class Resolved:
    """Output tables (lists of rows) and the evidence behind the decisions."""

    venues: list[Row] = field(default_factory=list)
    editions: list[Row] = field(default_factory=list)
    works: list[Row] = field(default_factory=list)
    versions: list[Row] = field(default_factory=list)
    authors: list[Row] = field(default_factory=list)
    authorships: list[Row] = field(default_factory=list)
    institutions: list[Row] = field(default_factory=list)
    citations: list[Row] = field(default_factory=list)
    matches: list[Row] = field(default_factory=list)  # core_version_match
    pair_rows: list[Row] = field(default_factory=list)  # core_version_pair (not "ignored")
    # evidence for reports and checks
    pairs: list[PairScore] = field(default_factory=list)
    blocked: list[PairScore] = field(default_factory=list)
    author_links: dict[str, AuthorLink] = field(default_factory=dict)
    unlinked_authors: list[UnlinkedAuthor] = field(default_factory=list)
    rejected_matches: list[Row] = field(default_factory=list)
    version_of_key: dict[str, str] = field(default_factory=dict)  # dblp_key -> version_id
    work_of_key: dict[str, str] = field(default_factory=dict)  # dblp_key -> work_id
    primary_key_of_work: dict[str, str] = field(default_factory=dict)  # work_id -> dblp_key
    stats: dict[str, Any] = field(default_factory=dict)


def _orcid(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().rsplit("/", 1)[-1].upper() or None


def _max_or_none(values: list[int | None]) -> int | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def resolve_corpus(
    inputs: Inputs,
    cfg: ResolveConfig,
    venue_registry: VenueRegistry,
    registry: IdRegistry,
    facts: VenueFacts | None = None,
) -> Resolved:
    out = Resolved()

    # -- 1. venues, editions ------------------------------------------------------------------
    venue_atlas = {v.id: registry.get_or_mint("venue", "config", v.id) for v in venue_registry}
    out.venues = build_venue_rows(venue_registry, lambda vid: venue_atlas[vid])
    edition_atlas = {
        e["edition_key"]: registry.get_or_mint("edition", "dblp", e["edition_key"])
        for e in inputs.editions
    }
    unknown_venues = sorted({e["venue_id"] for e in inputs.editions} - set(venue_atlas))
    if unknown_venues:
        raise ResolveError(f"staging has venues missing from venues.yaml: {unknown_venues}")
    out.editions = build_edition_rows(
        inputs.editions,
        venue_atlas_id=venue_atlas,
        mint_edition=lambda key: edition_atlas[key],
        facts=facts,
    )
    editions_by_key = {e["edition_key"]: e for e in inputs.editions}

    papers = sorted((p for p in inputs.papers if not p["is_front_matter"]), key=_key)
    if len({p["dblp_key"] for p in papers}) != len(papers):
        raise ResolveError("stg_dblp_paper has duplicate dblp_key values")
    for p in papers:
        if p["edition_key"] not in edition_atlas:
            raise ResolveError(
                f"{p['dblp_key']}: edition {p['edition_key']} not in stg_dblp_edition"
            )
    version_atlas = {
        p["dblp_key"]: registry.get_or_mint("version", "dblp", p["dblp_key"]) for p in papers
    }
    out.version_of_key = dict(version_atlas)

    # -- indexes ----------------------------------------------------------------------------
    dblp_auth: dict[str, list[Row]] = defaultdict(list)
    for a in inputs.authorships:
        dblp_auth[a["dblp_key"]].append(a)
    for rows in dblp_auth.values():
        rows.sort(key=lambda r: r["position"])
    dblp_author_by_pid = {a["pid"]: a for a in inputs.authors}
    oa_lookup = {r["dblp_key"]: r for r in inputs.oa_lookup}
    oa_work = {w["openalex_id"]: w for w in inputs.oa_works}
    oa_rows: dict[str, list[Row]] = defaultdict(list)
    for r in inputs.oa_authorships:
        oa_rows[r["openalex_id"]].append(r)
    s2_lookup = {r["dblp_key"]: r for r in inputs.s2_lookup}
    s2_paper = {p["s2_corpus_id"]: p for p in inputs.s2_papers}
    crossref = {normalise_doi(r["doi"]): r for r in inputs.crossref if r.get("doi")}

    markers = cfg.versions.strip_title_markers

    # -- 2. attach source records -----------------------------------------------------------
    accepted: dict[str, dict[str, SourceMatch]] = {}
    oa_ext: dict[str, list[ExternalAuthor]] = {}
    for p in papers:
        key = p["dblp_key"]
        authors = dblp_auth.get(key, [])
        paper = {
            "dblp_key": key,
            "title": p["title"],
            "year": p["edition_year"] or p["year"],
            "doi": p.get("doi"),
            "first_author": authors[0]["name_raw"] if authors else None,
        }
        found: dict[str, SourceMatch] = {}
        look = oa_lookup.get(key)
        work = oa_work.get(look["openalex_id"]) if look and look.get("openalex_id") else None
        ext = None
        if work is not None:
            ext = oa_ext.setdefault(
                work["openalex_id"], group_external_authors(oa_rows.get(work["openalex_id"], []))
            )
        first = ext[0].names[0] if ext and ext[0].names else None
        for source, result in (
            ("openalex", match_openalex(paper, look, work, first, cfg.source_match, markers)),
            (
                "s2",
                match_s2(
                    paper,
                    s2_lookup.get(key),
                    s2_paper.get((s2_lookup.get(key) or {}).get("s2_corpus_id")),
                    cfg.source_match,
                    markers,
                ),
            ),
            (
                "crossref",
                match_crossref(paper, crossref.get(normalise_doi(p.get("doi")))),
            ),
        ):
            if result.accepted is not None:
                found[source] = result.accepted
            elif result.rejected is not None:
                out.rejected_matches.append(
                    {"dblp_key": key, "source": source, "reason": result.rejected}
                )
        accepted[key] = found

    # -- 3. authors -------------------------------------------------------------------------
    alignments: dict[str, list[Alignment]] = {}
    evidence: list[tuple[str, str, str, bool]] = []
    for p in papers:
        key = p["dblp_key"]
        oa = accepted[key].get("openalex")
        if oa is None:
            continue
        ext = oa_ext[oa.external_id]
        aligned = align_authors(dblp_auth.get(key, []), ext, cfg.authors)
        alignments[key] = aligned
        for al in aligned:
            if al.external is None or not al.external.author_id:
                continue
            dblp_orcid = _orcid((dblp_author_by_pid.get(al.pid) or {}).get("orcid"))
            orcid_ok = bool(dblp_orcid) and dblp_orcid == _orcid(al.external.orcid)
            evidence.append((key, al.external.author_id, al.pid, orcid_ok))
    out.author_links, out.unlinked_authors = map_external_authors(evidence, cfg.authors)

    used_pids = {a["pid"] for rows in dblp_auth.values() for a in rows}
    missing = sorted(used_pids - set(dblp_author_by_pid))
    if missing:
        raise ResolveError(f"authorships name PIDs without an author record: {missing[:5]}")
    raw_names: dict[str, set[str]] = defaultdict(set)
    for rows in dblp_auth.values():
        for a in rows:
            raw_names[a["pid"]].add(a["name_raw"])
    author_atlas = {pid: registry.get_or_mint("author", "dblp", pid) for pid in sorted(used_pids)}
    out.authors = build_author_rows(
        (dblp_author_by_pid[pid] for pid in sorted(used_pids)),
        {k: v for k, v in out.author_links.items() if v.pid in used_pids},
        lambda pid: author_atlas[pid],
        raw_names=raw_names,
    )

    # -- 4. versions into works -------------------------------------------------------------
    oa_owner: dict[str, list[str]] = defaultdict(list)
    s2_owner: dict[int, list[str]] = defaultdict(list)
    for key, found in accepted.items():
        if "openalex" in found:
            oa_owner[found["openalex"].external_id].append(key)
        if "s2" in found:
            s2_owner[int(found["s2"].external_id)].append(key)
    cites: dict[str, set[str]] = defaultdict(set)
    for r in inputs.oa_references:
        for a in oa_owner.get(r["citing_openalex_id"], ()):
            cites[a].update(oa_owner.get(r["cited_openalex_id"], ()))
    for r in inputs.s2_references:
        for a in s2_owner.get(r["citing_corpus_id"], ()):
            cites[a].update(s2_owner.get(r["cited_corpus_id"], ()))
    for key in cites:
        cites[key].discard(key)

    refs: list[VersionRef] = []
    for p in papers:
        key = p["dblp_key"]
        venue = venue_registry.get(p["venue_id"])
        found = accepted[key]
        external = {(s, m.external_id) for s, m in found.items() if s in ("openalex", "s2")}
        named: set[str] = set()
        if "s2" in found:
            other = (s2_lookup.get(key) or {}).get("s2_dblp_key")
            if other and other != key:
                named.add(other)
        embedding = (inputs.embeddings.get(key) or {}).get("vector")
        refs.append(
            VersionRef(
                key=key,
                title=p["title"],
                year=int(p["edition_year"] or p["year"]),
                venue_id=p["venue_id"],
                edition_id=p["edition_key"],
                kind=KIND_OF_VENUE[venue.kind],
                authors=frozenset(a["pid"] for a in dblp_auth.get(key, [])),
                doi=normalise_doi(p.get("doi")),
                embedding=tuple(embedding) if embedding is not None else None,
                external=frozenset(external),
                named_keys=frozenset(named),
                cites=frozenset(cites.get(key, ())),
                special_issue_of=venue.special_issue_of,
            )
        )
    ref_by_key = {r.key: r for r in refs}
    cfg_v = cfg.versions
    out.pairs = [score_pair(a, b, cfg_v) for a, b in candidate_pairs(refs, cfg_v)]
    grouping: Grouping = group_versions(refs, out.pairs, cfg_v)
    out.blocked = grouping.blocked
    blocked_keys = {(b.earlier, b.later) for b in grouping.blocked}
    out.pair_rows = sorted(
        (
            {
                "earlier_version_id": version_atlas[x.earlier],
                "later_version_id": version_atlas[x.later],
                "score": x.score,
                "verdict": "blocked" if (x.earlier, x.later) in blocked_keys else x.verdict,
                "method": x.method,
                "title": x.features.get("title"),
                "authors": x.features.get("authors"),
                "embedding": x.features.get("embedding"),
                "extra": x.features.get("extra"),
                "reasons": "; ".join(x.reasons) or None,
            }
            for x in out.pairs
            if x.verdict != "ignored"
        ),
        key=lambda r: (r["earlier_version_id"], r["later_version_id"]),
    )

    single = {key: registry.get_or_mint("work", "dblp", key) for key in ref_by_key}
    try:
        for key, founder in sorted(grouping.group_of.items()):
            if key != founder:
                registry.merge(single[key], single[founder])
    except RegistryError as exc:
        raise ResolveError(
            f"the ID registry holds a merge that conflicts with this run: {exc}. "
            "An ID is never reused, so decide by hand which work survives."
        ) from exc
    out.work_of_key = {key: registry.resolve(single[key]) for key in single}
    work_to_group: dict[str, str] = {}
    for key, founder in grouping.group_of.items():
        wid = out.work_of_key[key]
        if work_to_group.setdefault(wid, founder) != founder:
            raise ResolveError(
                f"registry puts versions of different works under {wid} (e.g. {key}); "
                "it still holds a merge the current rules no longer produce"
            )

    members: dict[str, list[str]] = defaultdict(list)
    for key, founder in grouping.group_of.items():
        members[founder].append(key)

    # -- 5. rows -----------------------------------------------------------------------------
    paper_by_key = {p["dblp_key"]: p for p in papers}
    version_rows: list[Row] = []
    for p in papers:
        key = p["dblp_key"]
        found = accepted[key]
        oa = found.get("openalex")
        w = oa_work.get(oa.external_id) if oa else None
        cr = crossref.get(normalise_doi(p.get("doi"))) if "crossref" in found else None
        edition = editions_by_key[p["edition_key"]]
        pages = (cr or {}).get("page") or p.get("pages")
        pair = grouping.attach.get(key)
        doi = normalise_doi(p.get("doi"))
        version_rows.append(
            {
                "version_id": version_atlas[key],
                "work_id": out.work_of_key[key],
                "edition_id": edition_atlas[p["edition_key"]],
                "venue_id": venue_atlas[p["venue_id"]],
                "year": int(p["edition_year"] or p["year"]),
                "volume": (cr or {}).get("volume")
                or (w or {}).get("volume")
                or edition.get("volume"),
                "issue": (cr or {}).get("issue") or (w or {}).get("issue"),
                "pages": pages,
                "page_count": page_count(pages),
                "doi": doi,
                "dblp_key": key,
                "openalex_id": oa.external_id if oa else None,
                "s2_corpus_id": int(found["s2"].external_id) if "s2" in found else None,
                "crossref_type": (cr or {}).get("crossref_type"),
                "zbmath_id": None,
                "url_landing": (w or {}).get("landing_page_url")
                or (f"https://doi.org/{doi}" if doi else None),
                "url_oa": (w or {}).get("oa_url") if (w or {}).get("is_oa") else None,
                "merge_confidence": pair.score if pair else 1.0,
                "merge_method": pair.method if pair else "anchor",
            }
        )
        for source, m in sorted(found.items()):
            out.matches.append(
                {
                    "version_id": version_atlas[key],
                    "source": source,
                    "external_id": m.external_id,
                    "method": m.method,
                    "confidence": m.confidence,
                    "title_similarity": m.title_similarity,
                    "year_diff": m.year_diff,
                    "first_author_agrees": m.first_author_agrees,
                }
            )
    version_rows.sort(key=lambda r: r["version_id"])
    out.versions = version_rows
    out.matches.sort(key=lambda r: (r["version_id"], r["source"]))

    # authorships and institutions
    inst_names: dict[str, Counter[str]] = defaultdict(Counter)
    inst_country: dict[str, Counter[str]] = defaultdict(Counter)
    authorship_rows: list[Row] = []
    for p in papers:
        key = p["dblp_key"]
        by_pos = {al.dblp_position: al for al in alignments.get(key, [])}
        for a in dblp_auth.get(key, []):
            al = by_pos.get(a["position"])
            ext = al.external if al else None
            inst = institution_of(ext)
            affiliation = " | ".join(ext.raw_affiliations) if ext and ext.raw_affiliations else None
            if inst:
                if inst["name"]:
                    inst_names[inst["id"]][inst["name"]] += 1
                if inst["country"]:
                    inst_country[inst["id"]][inst["country"]] += 1
            authorship_rows.append(
                {
                    "version_id": version_atlas[key],
                    "author_id": author_atlas[a["pid"]],
                    "position": int(a["position"]),
                    "raw_name": a["name_raw"],
                    "affiliation_raw": affiliation,
                    "institution_id": inst["id"] if inst else None,
                    "country_code": inst["country"] if inst else None,
                    "source": "dblp+openalex" if (inst or affiliation) else "dblp",
                }
            )
    authorship_rows.sort(key=lambda r: (r["version_id"], r["position"]))
    out.authorships = authorship_rows
    out.institutions = [
        {
            "institution_id": inst_id,
            "name": sorted(names.items(), key=lambda kv: (-kv[1], kv[0]))[0][0],
            "country_code": (
                sorted(inst_country[inst_id].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
                if inst_country[inst_id]
                else None
            ),
        }
        for inst_id, names in sorted(inst_names.items())
    ]

    # citations
    oa_to_work: dict[str, str] = {}
    s2_to_work: dict[int, str] = {}
    ambiguous = {"openalex": 0, "s2": 0}
    for oa_id, keys in oa_owner.items():
        works = {out.work_of_key[k] for k in keys}
        if len(works) == 1:
            oa_to_work[oa_id] = next(iter(works))
        else:
            ambiguous["openalex"] += 1
    for corpus_id, keys in s2_owner.items():
        works = {out.work_of_key[k] for k in keys}
        if len(works) == 1:
            s2_to_work[corpus_id] = next(iter(works))
        else:
            ambiguous["s2"] += 1
    out.citations, cstats = build_citation_rows(
        ((r["citing_openalex_id"], r["cited_openalex_id"]) for r in inputs.oa_references),
        ((r["citing_corpus_id"], r["cited_corpus_id"]) for r in inputs.s2_references),
        oa_to_work,
        s2_to_work,
    )
    in_corpus: Counter[str] = Counter(r["cited_work_id"] for r in out.citations)

    # works
    work_rows: list[Row] = []
    tier_a = cfg.scope
    for founder, keys in sorted(members.items()):
        keys = sorted(keys)
        wid = out.work_of_key[founder]
        primary = primary_version(ref_by_key[k] for k in keys)
        out.primary_key_of_work[wid] = primary.key
        p = paper_by_key[primary.key]
        sources = {"dblp"}
        counts: list[int | None] = []
        language = None
        has_abstract = False
        for k in keys:
            found = accepted[k]
            sources.update(found)
            oa = found.get("openalex")
            if oa:
                w = oa_work[oa.external_id]
                counts.append(w.get("cited_by_count"))
                language = language or w.get("language")
            if "s2" in found:
                counts.append(s2_paper[int(found["s2"].external_id)].get("citation_count"))
            if "crossref" in found:
                cr = crossref[normalise_doi(paper_by_key[k].get("doi"))]
                counts.append(cr.get("is_referenced_by_count"))
                language = language or cr.get("language")
            has_abstract = has_abstract or k in inputs.abstracts
        work_rows.append(
            {
                "work_id": wid,
                "title": p["title"],
                "title_norm": p["title_norm"],
                "year": min(ref_by_key[k].year for k in keys),
                "primary_version_id": version_atlas[primary.key],
                "work_type": WORK_TYPE[primary.kind],
                "is_survey": None,
                "survey_confidence": None,
                "language": language,
                "has_abstract": has_abstract,
                "cited_by_count": _max_or_none(counts),
                "cited_by_in_corpus": in_corpus.get(wid, 0),
                "scope_status": tier_a.tier_a_status,
                "scope_score": tier_a.tier_a_score,
                "scope_reason": tier_a.tier_a_reason,
                "provenance": {"sources": sorted(sources), "n_versions": len(keys)},
            }
        )
    work_rows.sort(key=lambda r: r["work_id"])
    out.works = work_rows

    out.stats = {
        "venues": len(out.venues),
        "editions": len(out.editions),
        "papers": len(papers),
        "works": len(out.works),
        "versions": len(out.versions),
        "merged_versions": sum(1 for k, f in grouping.group_of.items() if k != f),
        "pairs_scored": len(out.pairs),
        "pairs_merge": sum(1 for x in out.pairs if x.verdict == "merge"),
        "pairs_uncertain": sum(1 for x in out.pairs if x.verdict == "uncertain"),
        "pairs_vetoed": sum(1 for x in out.pairs if x.verdict == "vetoed"),
        "merges_blocked": len(out.blocked),
        "authors": len(out.authors),
        "authorships": len(out.authorships),
        "institutions": len(out.institutions),
        "openalex_authors_linked": len(out.author_links),
        "openalex_authors_unlinked": len(out.unlinked_authors),
        "rejected_source_matches": len(out.rejected_matches),
        "ambiguous_openalex_ids": ambiguous["openalex"],
        "ambiguous_s2_ids": ambiguous["s2"],
        **{f"citation_{k}": v for k, v in cstats.items()},
    }
    return out


def _key(paper: Mapping[str, Any]) -> str:
    return paper["dblp_key"]
