"""Seed lists for the taxonomy (PLAN §9.1 step 1): CCS subtree, MSC codes, OpenAlex topics.

* ``ccs.yaml`` is *generated* from the SKOS file ACM publishes (a person downloads it, because
  the ACM site refuses automated clients); only the subtree named in ``config/taxonomy.yaml`` is
  kept. ACM holds the copyright of the CCS and allows free use for education and research, so the
  file carries ids and labels of the relevant subtree only, with the source and terms stated.
* ``msc.yaml`` is written by hand (our own wording; codes are cross-references).
* ``openalex_topics.yaml`` is *generated* from the topics the pilot works received (CC0).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import duckdb
import yaml

from flatatlas.settings import PROJECT_ROOT
from flatatlas.taxonomy.config import SeedsConfig

SEEDS_DIR = PROJECT_ROOT / "taxonomy" / "seeds"

NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
_RDF_ABOUT = f"{{{NS['rdf']}}}about"
_RDF_RESOURCE = f"{{{NS['rdf']}}}resource"
_ID_IN_URI = re.compile(r"(\d{5,10}(?:\.\d{5,10})*)(?!.*\d{5,10}(?:\.\d{5,10})*)")

CCS_NOTE = (
    "ACM Computing Classification System 2012 (https://dl.acm.org/ccs). ACM holds the copyright; "
    "the CCS is free to use for educational and research purposes (https://www.acm.org/about/"
    "class/2012). This file keeps the ids and labels of the formal-languages subtree only, as "
    "cross-references; topic names and descriptions in the Atlas are our own."
)


class SeedError(ValueError):
    pass


def concept_id(uri: str) -> str | None:
    """The CCS concept id inside a concept URI (the last run of dotted 8-digit groups)."""
    found = _ID_IN_URI.search(uri)
    return found.group(1) if found else None


def parse_ccs_skos(xml_text: str) -> list[dict[str, Any]]:
    """All concepts of the SKOS file: ``{id, label, parents}``, sorted by id."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SeedError(f"the CCS file is not valid XML: {exc}") from None
    nodes: dict[str, dict[str, Any]] = {}
    for concept in root.iter(f"{{{NS['skos']}}}Concept"):
        cid = concept_id(concept.get(_RDF_ABOUT, ""))
        label = None
        for pref in concept.findall("skos:prefLabel", NS):
            lang = pref.get(f"{{{NS['xml']}}}lang", "en")
            if lang.startswith("en") and pref.text:
                label = pref.text.strip()
        if cid is None or label is None:
            continue
        node = nodes.setdefault(cid, {"id": cid, "label": label, "parents": set()})
        for broader in concept.findall("skos:broader", NS):
            parent = concept_id(broader.get(_RDF_RESOURCE, ""))
            if parent:
                node["parents"].add(parent)
    # ``narrower`` links are the same relation seen from the parent.
    for concept in root.iter(f"{{{NS['skos']}}}Concept"):
        cid = concept_id(concept.get(_RDF_ABOUT, ""))
        if cid not in nodes:
            continue
        for narrower in concept.findall("skos:narrower", NS):
            child = concept_id(narrower.get(_RDF_RESOURCE, ""))
            if child in nodes:
                nodes[child]["parents"].add(cid)
    return [
        {"id": n["id"], "label": n["label"], "parents": sorted(n["parents"])}
        for _, n in sorted(nodes.items())
    ]


def select_ccs_subtree(
    nodes: list[dict[str, Any]], subtrees: list[str], single: list[str]
) -> list[dict[str, Any]]:
    """Concepts under any ``subtrees`` label (with that concept), plus the ``single`` concepts.

    Every label must match at least one concept, otherwise the file is not the one expected.
    """
    by_id = {n["id"]: n for n in nodes}
    children: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        for p in n["parents"]:
            children[p].append(n["id"])
    by_label: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        by_label[n["label"].casefold()].append(n["id"])

    keep: set[str] = set()
    for label in subtrees:
        roots = by_label.get(label.casefold())
        if not roots:
            raise SeedError(f"no CCS concept is labelled {label!r}")
        stack = list(roots)
        while stack:
            current = stack.pop()
            if current not in keep:
                keep.add(current)
                stack.extend(children.get(current, []))
    for label in single:
        ids = by_label.get(label.casefold())
        if not ids:
            raise SeedError(f"no CCS concept is labelled {label!r}")
        keep.update(ids)
    # Parents outside the kept set are dropped: the seed lists concepts, not the whole tree above.
    return [
        {
            "id": i,
            "label": by_id[i]["label"],
            "parents": [p for p in by_id[i]["parents"] if p in keep],
        }
        for i in sorted(keep)
    ]


def ccs_yaml(selected: list[dict[str, Any]], *, source_file: str) -> dict[str, Any]:
    return {"source": CCS_NOTE, "downloaded_file": source_file, "concepts": selected}


def openalex_seed(con: duckdb.DuckDBPyConnection, min_works: int) -> dict[str, Any]:
    """Topics (and, apart, keywords) the pilot works received, with counts (CC0 data)."""
    rows = con.execute(
        "SELECT kind, topic_id, name, subfield, field, domain, score, openalex_id "
        "FROM stg_openalex_topic ORDER BY kind, topic_id, openalex_id"
    ).fetchall()
    topics: dict[str, dict[str, Any]] = {}
    scores: dict[str, list[float]] = defaultdict(list)
    keywords: Counter[str] = Counter()
    for kind, topic_id, name, subfield, field, domain, score, _wid in rows:
        if kind == "topic":
            topics.setdefault(
                topic_id,
                {
                    "id": topic_id,
                    "name": name,
                    "subfield": subfield,
                    "field": field,
                    "domain": domain,
                },
            )
            scores[topic_id].append(float(score or 0.0))
        elif kind == "keyword" and name:
            keywords[name] += 1
    listed = []
    for topic_id, t in sorted(topics.items()):
        n = len(scores[topic_id])
        if n >= min_works:
            listed.append({**t, "n_works": n, "mean_score": round(sum(scores[topic_id]) / n, 3)})
    listed.sort(key=lambda t: (-t["n_works"], t["id"]))
    kw = [
        {"name": name, "n_works": n}
        for name, n in sorted(keywords.items(), key=lambda kv: (-kv[1], kv[0]))
        if n >= min_works
    ]
    return {
        "source": "OpenAlex topics and keywords of the pilot works (CC0, https://openalex.org)",
        "topics": listed,
        # Machine-generated and sparse: candidates only, never merged into the taxonomy (D-65).
        "keywords": {"trusted": False, "items": kw},
    }


def load_msc(path: Path | None = None) -> list[dict[str, Any]]:
    data = yaml.safe_load((path or SEEDS_DIR / "msc.yaml").read_text(encoding="utf-8"))
    return list(data["codes"])


def dump_yaml(data: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# Generated by `flatatlas taxonomy seeds`. Do not edit by hand (CLAUDE.md rule 5).\n"
    path.write_text(
        header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    return path


def build_seeds(
    con: duckdb.DuckDBPyConnection | None,
    cfg: SeedsConfig,
    *,
    ccs_file: Path | None,
    out_dir: Path = SEEDS_DIR,
) -> dict[str, int]:
    """Write ``ccs.yaml`` (when the SKOS file is given) and ``openalex_topics.yaml``."""
    counts: dict[str, int] = {}
    if ccs_file is not None:
        nodes = parse_ccs_skos(ccs_file.read_text(encoding="utf-8"))
        selected = select_ccs_subtree(nodes, cfg.ccs_subtrees, cfg.ccs_single)
        dump_yaml(ccs_yaml(selected, source_file=ccs_file.name), out_dir / "ccs.yaml")
        counts["ccs_concepts_in_file"] = len(nodes)
        counts["ccs_concepts_kept"] = len(selected)
    if con is not None:
        seed = openalex_seed(con, cfg.openalex_min_works)
        dump_yaml(seed, out_dir / "openalex_topics.yaml")
        counts["openalex_topics"] = len(seed["topics"])
        counts["openalex_keywords"] = len(seed["keywords"]["items"])
    return counts
