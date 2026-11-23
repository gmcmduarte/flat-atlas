"""The shapes of the static JSON the site reads (PLAN §11.2). One source for three things: the
exporter validates what it writes against these models, ``typegen`` turns them into JSON Schemas
and into ``web/src/lib/data/types.ts``, and a test checks the committed copies are current.

Field names are the column names of the release, in snake_case on purpose, so the JSON needs no
renaming. Keep the models plain: objects, lists, literals, ``X | None`` and ``dict[str, float]``
are all ``typegen`` understands.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EdgeType = Literal["subtopic-of", "related", "builds-on", "shared-community"]
LateralEdgeType = Literal["related", "builds-on", "shared-community"]
TagStatus = Literal["tagged", "low_confidence", "untagged"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TopicRef(_Model):
    topic_id: str
    name: str


class Topic(_Model):
    """One row of ``topics.json``."""

    topic_id: str
    name: str
    description: str
    level: int = Field(description="0 = top-level bubble.")
    parents: list[str]
    children: list[str]
    paper_count: int = Field(description="Works with a normal tag in the topic or below it.")
    volume: float = Field(description="Sum of the rolled-up confidences (bubble size).")
    n_low_confidence: int = Field(description="Weakly matched works, not in paper_count.")


class TopicSummary(_Model):
    topic_id: str
    name: str
    description: str
    level: int
    paper_count: int
    volume: float
    n_low_confidence: int


class TopicEdge(_Model):
    """A lateral edge as seen from the topic whose page it is on."""

    topic_id: str
    name: str
    edge_type: LateralEdgeType
    direction: Literal["out", "in", "both"] = Field(
        description="out: this topic builds on the other; in: the other builds on this one."
    )
    weight: float
    confidence: float = Field(description="Not comparable across edge types.")


class TopicEdges(_Model):
    related: list[TopicEdge]
    builds_on: list[TopicEdge] = Field(alias="builds-on")
    shared_community: list[TopicEdge] = Field(alias="shared-community")


class Provenance(_Model):
    method: str
    signals: dict[str, float] = Field(description="Signal name to score, for the tooltip.")
    tagger_version: str
    taxonomy_version: str
    flags: list[str]


class Tag(_Model):
    """A work-topic tag: never shown without its confidence and provenance."""

    topic_id: str
    topic_name: str
    confidence: float
    rank: int
    is_primary: bool
    derived: bool = Field(description="True for ancestor rows added by closure.")
    provenance: Provenance


class TopicPaper(_Model):
    work_id: str
    title: str
    year: int
    venue_acronym: str
    authors: list[str] = Field(description="Names of the first authors (at most 3).")
    n_authors: int
    confidence: float
    cited_by_count: int
    low_confidence: bool


class TopicAuthor(_Model):
    author_id: str
    name: str
    score: float


class YearPoint(_Model):
    year: int
    papers: int
    volume: float


class TopicPage(_Model):
    """``topic/<id>.json``."""

    topic: TopicSummary
    parents: list[TopicRef]
    children: list[TopicRef]
    edges: TopicEdges
    top_papers: list[TopicPaper]
    key_authors: list[TopicAuthor]
    year_series: list[YearPoint]
    fixture: bool | None = None


class WorkVenue(_Model):
    venue_id: str
    acronym: str


class WorkAuthor(_Model):
    author_id: str
    name: str
    position: int


class WorkLinks(_Model):
    dblp: str | None
    openalex: str | None
    doi: str | None
    open_access: str | None


class WorkSummary(_Model):
    """A work as listed on another page (references, citers, an author's or venue's papers)."""

    work_id: str
    title: str
    year: int
    venue_acronym: str
    authors: list[str] = Field(description="Names of the first authors (at most 3).")
    n_authors: int
    cited_by_count: int


class WorkVersion(_Model):
    """One published version of a work (a conference paper and its journal version, say)."""

    venue_acronym: str
    year: int
    volume: str | None
    pages: str | None
    doi: str | None
    url: str | None


class Work(_Model):
    """One entry of a ``works/<shard>.json`` file."""

    work_id: str
    title: str
    year: int
    work_type: str
    venue: WorkVenue
    authors: list[WorkAuthor]
    doi: str | None
    links: WorkLinks
    cited_by_count: int
    tag_status: TagStatus
    tags: list[Tag]
    versions: list[WorkVersion] = Field(description="All versions; the first is the primary one.")
    references: list[WorkSummary] = Field(description="Works in the corpus that this work cites.")
    cited_by: list[WorkSummary] = Field(description="Works in the corpus that cite this work.")
    fixture: bool | None = None


class AuthorTopic(_Model):
    topic_id: str
    score: float


class Coauthor(_Model):
    author_id: str
    name: str
    n_papers: int = Field(description="Papers written together.")


class Author(_Model):
    """One entry of an ``authors/<shard>.json`` file."""

    author_id: str
    display_name: str
    name_variants: list[str]
    dblp_pid: str | None
    orcid: str | None
    topics: list[AuthorTopic]
    work_ids: list[str]
    papers: list[WorkSummary] = Field(description="Newest first.")
    coauthors: list[Coauthor] = Field(description="The 20 most frequent.")
    fixture: bool | None = None


class VenueTopic(_Model):
    topic_id: str
    name: str
    papers: int


class VenueYear(_Model):
    year: int
    papers: int


class Venue(_Model):
    """``venue/<id>.json``."""

    venue_id: str
    acronym: str
    name: str
    kind: Literal["conference", "journal", "book-series"]
    tier: Literal["core", "broad", "other"]
    first_year: int
    last_year: int | None
    successor_of: list[str]
    homepage: str | None
    n_works: int
    year_series: list[VenueYear]
    top_topics: list[VenueTopic] = Field(description="Level-0 topics with most papers, at most 10.")
    top_papers: list[WorkSummary] = Field(description="The 30 most cited works.")
    fixture: bool | None = None


class MapNode(_Model):
    topic_id: str
    parent_id: str | None
    level: int
    x: float
    y: float
    r: float
    ghost_parents: list[str]


class MapLayout(_Model):
    """``map.json``: precomputed layout, one node per topic."""

    nodes: list[MapNode]


class SearchTopic(_Model):
    topic_id: str
    name: str
    aliases: list[str]


class SearchAuthor(_Model):
    author_id: str
    name: str


class SearchVenue(_Model):
    venue_id: str
    name: str
    acronym: str


class SearchWork(_Model):
    work_id: str
    title: str
    year: int


class SearchIndex(_Model):
    """``search/index.json``: the raw documents the client indexes."""

    topics: list[SearchTopic]
    authors: list[SearchAuthor]
    venues: list[SearchVenue]
    works: list[SearchWork]


class SearchResults(_Model):
    topics: list[TopicRef]
    authors: list[SearchAuthor]
    venues: list[SearchVenue]
    works: list[SearchWork]


class DataVenue(_Model):
    """One venue of the release, as ``meta.json`` lists it (the release banner names them)."""

    venue_id: str
    acronym: str
    name: str
    first_year: int
    last_year: int | None
    successor_of: list[str] = Field(description="Venue IDs this venue continues (a rename).")


class DataInfo(_Model):
    """``meta.json``: which release the site data comes from (banner, footer, About, Cite)."""

    release: str
    date: str
    tagger_version: str
    taxonomy_version: str
    aggregate_version: str
    works: int
    works_by_tag_status: dict[str, int]
    topics: int
    venues: list[DataVenue]
    source_fetch_dates: dict[str, str]
    fixture: bool | None = None


# The models that are written to disk as one file each (name of the schema file).
SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "topics": Topic,
    "topic-page": TopicPage,
    "work": Work,
    "author": Author,
    "venue": Venue,
    "map": MapLayout,
    "search-index": SearchIndex,
    "meta": DataInfo,
}

# Everything that appears in types.ts, in this order.
TYPE_MODELS: list[type[BaseModel]] = [
    TopicRef,
    Topic,
    TopicSummary,
    TopicEdge,
    TopicEdges,
    Provenance,
    Tag,
    TopicPaper,
    TopicAuthor,
    YearPoint,
    TopicPage,
    WorkVenue,
    WorkAuthor,
    WorkLinks,
    WorkSummary,
    WorkVersion,
    Work,
    AuthorTopic,
    Coauthor,
    Author,
    VenueTopic,
    VenueYear,
    Venue,
    MapNode,
    MapLayout,
    SearchTopic,
    SearchAuthor,
    SearchVenue,
    SearchWork,
    SearchIndex,
    SearchResults,
    DataVenue,
    DataInfo,
]
