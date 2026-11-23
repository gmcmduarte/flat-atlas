import type { MapLayout, Topic } from '#lib/data/index.js';
import { buildIndex } from './model';

/** A small tree for the tests: roots a, b; a has children a1, a2; a1 has a1x; b has b1; a2 also under b. */
export function sampleIndex() {
	const node = (
		topic_id: string,
		parent_id: string | null,
		level: number,
		r: number,
		ghost_parents: string[] = []
	) => ({ topic_id, parent_id, level, x: 0, y: 0, r, ghost_parents });
	const layout: MapLayout = {
		nodes: [
			node('a', null, 0, 100),
			node('b', null, 0, 50),
			node('a1', 'a', 1, 30),
			node('a2', 'a', 1, 20, ['b']),
			node('a1x', 'a1', 2, 10),
			node('b1', 'b', 1, 15)
		]
	};
	const topics: Topic[] = layout.nodes.map((n) => ({
		topic_id: n.topic_id,
		name: n.topic_id.toUpperCase(),
		description: '',
		level: n.level,
		parents: n.parent_id ? [n.parent_id] : [],
		children: [],
		paper_count: 1,
		volume: n.r,
		n_low_confidence: 0
	}));
	return buildIndex(layout, topics);
}
