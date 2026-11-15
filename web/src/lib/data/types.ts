// Types for the data the site reads (PLAN §4, §11.2). Field names are snake_case on purpose: they
// are the column names of the exported release, so the JSON needs no renaming. Hand-written for
// now; PLAN §11.1 wants them generated from the schema later.

export type EdgeType = 'subtopic-of' | 'related' | 'builds-on' | 'shared-community';

/** Lateral edge types shown on a topic page (the backbone is shown as parents and children). */
export type LateralEdgeType = Exclude<EdgeType, 'subtopic-of'>;

export interface TopicRef {
	topic_id: string;
	name: string;
}

/** One row of `topics.json`. */
export interface Topic {
	topic_id: string;
	name: string;
	description: string;
	/** 0 = top-level bubble. */
	level: number;
	parents: string[];
	children: string[];
	paper_count: number;
}

/** A lateral edge as seen from the topic whose page it is on. */
export interface TopicEdge {
	topic_id: string;
	name: string;
	edge_type: LateralEdgeType;
	/** `out`: this topic builds on the other; `in`: the other builds on this one. */
	direction: 'out' | 'in' | 'both';
	weight: number;
	confidence: number;
}

export interface Provenance {
	method: string;
	/** Signal name to score, for the tooltip ("matched phrase ...; embedding 0.71"). */
	signals: Record<string, number>;
	tagger_version: string;
	taxonomy_version: string;
}

/** A work-topic tag (`tag_work_topic`): never shown without its confidence and provenance. */
export interface Tag {
	topic_id: string;
	topic_name: string;
	/** 0 to 1. */
	confidence: number;
	rank: number;
	is_primary: boolean;
	/** True for ancestor rows added by closure. */
	derived: boolean;
	provenance: Provenance;
}

export interface TopicPaper {
	work_id: string;
	title: string;
	year: number;
	venue_acronym: string;
	confidence: number;
	cited_by_count: number;
}

export interface TopicAuthor {
	author_id: string;
	name: string;
	score: number;
}

/** `topic/<id>.json`. */
export interface TopicPage {
	topic: Pick<Topic, 'topic_id' | 'name' | 'description' | 'level' | 'paper_count'>;
	parents: TopicRef[];
	children: TopicRef[];
	edges: Record<LateralEdgeType, TopicEdge[]>;
	top_papers: TopicPaper[];
	key_authors: TopicAuthor[];
	year_series: { year: number; papers: number }[];
	fixture?: boolean;
}

export interface Work {
	work_id: string;
	title: string;
	year: number;
	work_type: string;
	venue: { venue_id: string; acronym: string };
	authors: { author_id: string; name: string; position: number }[];
	doi: string | null;
	links: {
		dblp: string | null;
		openalex: string | null;
		doi: string | null;
		open_access: string | null;
	};
	cited_by_count: number;
	tags: Tag[];
	fixture?: boolean;
}

export interface Author {
	author_id: string;
	display_name: string;
	name_variants: string[];
	dblp_pid: string | null;
	orcid: string | null;
	topics: { topic_id: string; score: number }[];
	work_ids: string[];
	fixture?: boolean;
}

export interface Venue {
	venue_id: string;
	acronym: string;
	name: string;
	kind: 'conference' | 'journal' | 'book-series';
	tier: 'core' | 'broad' | 'other';
	first_year: number;
	last_year: number | null;
	successor_of: string[];
	homepage: string | null;
	fixture?: boolean;
}

/** `map.json`: precomputed layout, one node per topic. */
export interface MapNode {
	topic_id: string;
	parent_id: string | null;
	level: number;
	x: number;
	y: number;
	r: number;
}

export interface MapLayout {
	nodes: MapNode[];
}

export interface SearchResults {
	topics: TopicRef[];
	authors: { author_id: string; name: string }[];
	venues: { venue_id: string; name: string }[];
	works: { work_id: string; title: string }[];
}
