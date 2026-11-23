import type { MapLayout, MapNode, Topic } from '#lib/data/index.js';

/** One topic as the map knows it: layout from `map.json`, names and sizes from `topics.json`. */
export interface MapTopic {
	id: string;
	name: string;
	level: number;
	/** The primary parent (the layout puts the disc inside it). */
	parentId: string | null;
	ghostParents: string[];
	x: number;
	y: number;
	/** Radius in layout units. */
	r: number;
	volume: number;
	paperCount: number;
	/** Children drawn inside this topic's disc (those whose primary parent it is), biggest first. */
	children: string[];
	/** The level-0 ancestor, which gives the colour. */
	rootId: string;
}

export interface MapIndex {
	topics: Map<string, MapTopic>;
	/** Level-0 topics, biggest first. */
	roots: string[];
}

/**
 * Joins the layout and the topic list. A layout node without a topic row is kept with its id as
 * name (it should not happen on a verified export); a topic without a layout node is not drawn.
 */
export function buildIndex(layout: MapLayout, topics: Topic[]): MapIndex {
	const byId = new Map(topics.map((t) => [t.topic_id, t]));
	const nodes = new Map<string, MapNode>(layout.nodes.map((n) => [n.topic_id, n]));
	const out = new Map<string, MapTopic>();

	const rootOf = (id: string): string => {
		const seen = new Set<string>();
		let current = id;
		for (;;) {
			const parent = nodes.get(current)?.parent_id ?? null;
			if (parent === null || !nodes.has(parent) || seen.has(current)) return current;
			seen.add(current);
			current = parent;
		}
	};

	for (const node of layout.nodes) {
		const topic = byId.get(node.topic_id);
		out.set(node.topic_id, {
			id: node.topic_id,
			name: topic?.name ?? node.topic_id,
			level: node.level,
			parentId: node.parent_id && nodes.has(node.parent_id) ? node.parent_id : null,
			ghostParents: node.ghost_parents.filter((id) => nodes.has(id)),
			x: node.x,
			y: node.y,
			r: node.r,
			volume: topic?.volume ?? 0,
			paperCount: topic?.paper_count ?? 0,
			children: [],
			rootId: rootOf(node.topic_id)
		});
	}
	const bySize = (a: string, b: string) =>
		out.get(b)!.r - out.get(a)!.r || (a < b ? -1 : a > b ? 1 : 0);
	for (const t of out.values()) {
		if (t.parentId) out.get(t.parentId)!.children.push(t.id);
	}
	for (const t of out.values()) t.children.sort(bySize);
	const roots = [...out.values()].filter((t) => t.parentId === null).map((t) => t.id);
	roots.sort(bySize);
	return { topics: out, roots };
}

/** The topic's ancestors, nearest first, following primary parents. */
export function ancestorsOf(index: MapIndex, id: string): string[] {
	const out: string[] = [];
	let parent = index.topics.get(id)?.parentId ?? null;
	while (parent !== null && !out.includes(parent)) {
		out.push(parent);
		parent = index.topics.get(parent)?.parentId ?? null;
	}
	return out;
}

/** Whether `id` lies in the subtree of `ancestor` (not equal to it). */
export function isBelow(index: MapIndex, id: string, ancestor: string): boolean {
	return ancestorsOf(index, id).includes(ancestor);
}
