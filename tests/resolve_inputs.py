"""Small synthetic corpus for the resolve tests (importable as ``resolve_inputs``).

Venues: ``conf`` (a conference) and ``jour`` (a journal that publishes special issues of it).
Papers:

* ``conf/c/A19``  "Fast Regular Expression Matching (Extended Abstract)", authors Ann, Bob (2019)
* ``journals/j/A21`` "Fast Regular Expression Matching", same authors, journal 2021, cites A19:
  one work with two versions.
* ``conf/c/B19``  the same title, other authors (Cy, Di): another work.
* ``conf/c/P19a`` "Pumping Words I" and ``conf/c/P19b`` "Pumping Words II" (Ann, Bob, same
  edition): two works.
* ``conf/c/H19``  author "Ann Lee" (second PID with a homonym name): never merged with Ann.
"""

from __future__ import annotations

from typing import Any

from flatatlas.resolve.config import ResolveConfig, parse_resolve_config
from flatatlas.resolve.inputs import Inputs
from flatatlas.venues import VenueRegistry, parse_venues

VENUES = [
    {"id": "conf", "acronym": "CONF", "name": "Conference", "kind": "conference", "tier": "core"},
    {
        "id": "jour",
        "acronym": "JOUR",
        "name": "Journal",
        "kind": "journal",
        "tier": "core",
        "special_issue_of": "conf",
    },
]

CONFIG = {
    "versions": {
        "merge_min": 0.85,
        "report_min": 0.5,
        "weights": {"title": 0.45, "authors": 0.30, "embedding": 0.15, "extra": 0.10},
        "strip_title_markers": ["extended abstract", "full version"],
    }
}

VEC = [1.0, 0.0, 0.0]
NEAR = [0.98, 0.2, 0.0]  # cosine about 0.98 with VEC
FAR = [0.0, 1.0, 0.0]


def config() -> ResolveConfig:
    return parse_resolve_config(CONFIG)


def venue_registry() -> VenueRegistry:
    return parse_venues(VENUES)


def _paper(key: str, venue: str, edition: str, year: int, title: str, doi: str | None) -> dict:
    return {
        "dblp_key": key,
        "venue_id": venue,
        "edition_key": edition,
        "edition_year": year,
        "year": year,
        "title": title,
        "title_norm": " ".join(title.lower().split()),
        "pages": "1-10",
        "doi": doi,
        "is_front_matter": False,
    }


def _authorships(key: str, people: list[tuple[str, str]]) -> list[dict[str, Any]]:
    return [
        {"dblp_key": key, "position": i, "pid": pid, "name_raw": name}
        for i, (pid, name) in enumerate(people, start=1)
    ]


ANN = ("1/1", "Ann Lee 0001")
BOB = ("2/2", "Bob Stone")
CY = ("3/3", "Cy Young")
DI = ("4/4", "Di Prince")
ANN2 = ("5/5", "Ann Lee 0002")


def make_inputs() -> Inputs:
    inputs = Inputs()
    inputs.editions = [
        {"edition_key": "conf/c/2019", "venue_id": "conf", "year": 2019, "label": "CONF 2019",
         "volume": "100", "proceedings_doi": "10.1/proc"},
        {"edition_key": "journals/j/21", "venue_id": "jour", "year": 2021, "label": "vol. 21",
         "volume": "21", "proceedings_doi": None},
    ]  # fmt: skip
    inputs.papers = [
        _paper("conf/c/A19", "conf", "conf/c/2019", 2019,
               "Fast Regular Expression Matching (Extended Abstract)", "10.1/A19"),
        _paper("journals/j/A21", "jour", "journals/j/21", 2021,
               "Fast Regular Expression Matching", "10.2/A21"),
        _paper("conf/c/B19", "conf", "conf/c/2019", 2019,
               "Fast Regular Expression Matching", "10.1/B19"),
        _paper("conf/c/P19a", "conf", "conf/c/2019", 2019, "Pumping Words I", None),
        _paper("conf/c/P19b", "conf", "conf/c/2019", 2019, "Pumping Words II", None),
        _paper("conf/c/H19", "conf", "conf/c/2019", 2019, "Homonym Study", None),
    ]  # fmt: skip
    for key, people in {
        "conf/c/A19": [ANN, BOB],
        "journals/j/A21": [ANN, BOB],
        "conf/c/B19": [CY, DI],
        "conf/c/P19a": [ANN, BOB],
        "conf/c/P19b": [ANN, BOB],
        "conf/c/H19": [ANN2],
    }.items():
        inputs.authorships += _authorships(key, people)
    seen = {}
    for _key, rows in ((k, v) for k, v in {"x": [ANN, BOB, CY, DI, ANN2]}.items()):
        for pid, name in rows:
            seen[pid] = name
    inputs.authors = [
        {"pid": pid, "name": name, "name_variants": [], "orcid": None} for pid, name in seen.items()
    ]
    # Embeddings: A19 and A21 almost equal, everything else unrelated.
    for key, vec in {
        "conf/c/A19": VEC,
        "journals/j/A21": NEAR,
        "conf/c/B19": FAR,
        "conf/c/P19a": [0.0, 0.0, 1.0],
        "conf/c/P19b": [0.0, 0.0, 1.0],
        "conf/c/H19": [0.5, 0.5, 0.5],
    }.items():
        inputs.embeddings[key] = {
            "dblp_key": key,
            "model": "specter2",
            "source": "local",
            "s2_corpus_id": None,
            "input_kind": "title",
            "abstract_source": None,
            "vector": vec,
        }
    inputs.abstracts = {"conf/c/A19": ("openalex", "We match expressions fast.")}

    # OpenAlex knows A19 (by DOI) and A21 (by DOI); A21 cites A19.
    inputs.oa_lookup = [
        {"dblp_key": "conf/c/A19", "lookup_kind": "doi", "openalex_id": "W1",
         "match_method": "doi-exact", "match_confidence": 1.0},
        {"dblp_key": "journals/j/A21", "lookup_kind": "doi", "openalex_id": "W2",
         "match_method": "doi-exact", "match_confidence": 1.0},
    ]  # fmt: skip
    inputs.oa_works = [
        {"openalex_id": "W1", "doi": "https://doi.org/10.1/A19",
         "title": "Fast Regular Expression Matching",
         "publication_year": 2019, "language": "en", "cited_by_count": 7, "is_oa": True,
         "oa_url": "https://oa.example/1", "landing_page_url": "https://l.example/1",
         "volume": None, "issue": None},
        {"openalex_id": "W2", "doi": "10.2/a21", "title": "Fast Regular Expression Matching",
         "publication_year": 2021, "language": "en", "cited_by_count": 3, "is_oa": False,
         "oa_url": None, "landing_page_url": None, "volume": "21", "issue": "2"},
    ]  # fmt: skip
    inputs.oa_authorships = [
        {"openalex_id": "W1", "position": 0, "author_id": "A100", "author_name": "Ann Lee",
         "raw_author_name": "Ann Lee", "orcid": None, "institution_id": "I1",
         "institution_name": "Uni One", "ror": "01abc", "country_code": "PT",
         "raw_affiliation": "Uni One, Lisbon"},
        {"openalex_id": "W1", "position": 1, "author_id": "A200", "author_name": "Bob Stone",
         "raw_author_name": "Bob Stone", "orcid": None, "institution_id": "I2",
         "institution_name": "Uni Two", "ror": None, "country_code": "FR",
         "raw_affiliation": "Uni Two"},
        {"openalex_id": "W2", "position": 0, "author_id": "A100", "author_name": "Ann Lee",
         "raw_author_name": "Ann Lee", "orcid": None, "institution_id": None,
         "institution_name": None, "ror": None, "country_code": None, "raw_affiliation": None},
        {"openalex_id": "W2", "position": 1, "author_id": "A200", "author_name": "Bob Stone",
         "raw_author_name": "Bob Stone", "orcid": None, "institution_id": None,
         "institution_name": None, "ror": None, "country_code": None, "raw_affiliation": None},
    ]  # fmt: skip
    inputs.oa_references = [{"citing_openalex_id": "W2", "cited_openalex_id": "W1", "position": 0}]
    # Semantic Scholar knows A19 and B19; B19 cites A19. A21 is not there.
    inputs.s2_lookup = [
        {"dblp_key": "conf/c/A19", "status": "matched", "method": "doi", "s2_corpus_id": 10,
         "s2_dblp_key": "conf/c/A19"},
        {"dblp_key": "conf/c/B19", "status": "matched", "method": "title", "s2_corpus_id": 12,
         "s2_dblp_key": "conf/c/B19"},
    ]  # fmt: skip
    inputs.s2_papers = [
        {"s2_corpus_id": 10, "title": "Fast Regular Expression Matching", "year": 2019,
         "doi": "10.1/a19", "citation_count": 11},
        {"s2_corpus_id": 12, "title": "Fast Regular Expression Matching", "year": 2019,
         "doi": None, "citation_count": 1},
    ]  # fmt: skip
    inputs.s2_references = [{"citing_corpus_id": 12, "cited_corpus_id": 10}]
    inputs.crossref = [
        {"doi": "10.1/a19", "page": "11-22", "volume": "100", "issue": None,
         "crossref_type": "book-chapter", "language": None, "is_referenced_by_count": 9},
    ]  # fmt: skip
    return inputs


def write_staging(con, inputs: Inputs) -> None:
    """Store ``inputs`` as the staging and local tables the stage reads from DuckDB."""
    import pyarrow as pa

    from flatatlas.resolve.inputs import REQUIRED_TABLES

    def put(name: str, rows: list[dict]) -> None:
        con.register("_rows", pa.Table.from_pylist(rows))
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _rows")
        con.unregister("_rows")

    for attr, table in REQUIRED_TABLES.items():
        put(table, getattr(inputs, attr))
    put("local_embedding", list(inputs.embeddings.values()))
    put(
        "local_abstract",
        [
            {"dblp_key": k, "source": src, "text": text}
            for k, (src, text) in inputs.abstracts.items()
        ],
    )
