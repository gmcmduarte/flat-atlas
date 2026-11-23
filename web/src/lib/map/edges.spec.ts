import { describe, expect, it } from 'vitest';
import type { LateralEdgeType, TopicEdge, TopicPage } from '#lib/data/index.js';
import { aggregateEdges, ghostLinks, normaliseWeights, topPerNode, type MapEdge } from './edges';
import { sampleIndex } from './testIndex';
import { cutOf } from './visible';

const index = sampleIndex();

const edge = (
	topic_id: string,
	edge_type: LateralEdgeType,
	weight: number,
	direction: TopicEdge['direction'] = 'both'
): TopicEdge => ({ topic_id, name: topic_id, edge_type, direction, weight, confidence: 0.5 });

function page(id: string, edges: TopicEdge[]): TopicPage {
	const by = (t: LateralEdgeType) => edges.filter((e) => e.edge_type === t);
	return {
		topic: {
			topic_id: id,
			name: id,
			description: '',
			level: 0,
			paper_count: 1,
			volume: 1,
			n_low_confidence: 0
		},
		parents: [],
		children: [],
		edges: {
			related: by('related'),
			'builds-on': by('builds-on'),
			'shared-community': by('shared-community')
		},
		top_papers: [],
		key_authors: [],
		year_series: []
	};
}
const pages = (...p: TopicPage[]) => new Map(p.map((x) => [x.topic.topic_id, x]));

describe('aggregateEdges', () => {
	it('takes a stored edge between two bubbles as it is, once, from either page', () => {
		const cut = cutOf(index, []);
		const edges = aggregateEdges(
			index,
			cut,
			pages(page('a', [edge('b', 'related', 0.4)]), page('b', [edge('a', 'related', 0.4)])),
			'related'
		);
		expect(edges).toHaveLength(1);
		expect(edges[0]).toMatchObject({ from: 'a', to: 'b', weight: 0.4, rolledUp: 0 });
	});
	it('rolls an edge to a topic inside a collapsed bubble up to that bubble', () => {
		const cut = cutOf(index, []);
		const edges = aggregateEdges(
			index,
			cut,
			pages(page('b', [edge('a1x', 'related', 0.3)])),
			'related'
		);
		expect(edges).toHaveLength(1);
		expect(edges[0]).toMatchObject({ from: 'a', to: 'b', weight: 0.3, rolledUp: 1 });
	});
	it('keeps the strongest rolled-up edge, not the sum, and prefers a stored direct edge', () => {
		const cut = cutOf(index, []);
		const rolled = aggregateEdges(
			index,
			cut,
			pages(page('b', [edge('a1x', 'related', 0.3), edge('a2', 'related', 0.5)])),
			'related'
		);
		expect(rolled[0]).toMatchObject({ weight: 0.5, rolledUp: 2 });
		const direct = aggregateEdges(
			index,
			cut,
			pages(page('b', [edge('a2', 'related', 0.5), edge('a', 'related', 0.2)])),
			'related'
		);
		expect(direct[0]).toMatchObject({ weight: 0.2, rolledUp: 0 });
	});
	it('drops edges inside one bubble and edges to expanded parents', () => {
		const cut = cutOf(index, ['a']); // a1, a2, b; a is a hull
		const edges = aggregateEdges(
			index,
			cut,
			pages(page('a1', [edge('a1x', 'related', 0.9), edge('a', 'related', 0.9)])),
			'related'
		);
		expect(edges).toEqual([]);
	});
	it('only reads the requested type and keeps the direction of builds-on', () => {
		const cut = cutOf(index, []);
		const p = pages(
			page('a', [edge('b', 'builds-on', 0.2, 'out'), edge('b', 'related', 0.9)]),
			page('b', [edge('a', 'builds-on', 0.2, 'in')])
		);
		const builds = aggregateEdges(index, cut, p, 'builds-on');
		expect(builds).toHaveLength(1);
		expect(builds[0]).toMatchObject({ from: 'a', to: 'b', directed: true });
		const backwards = aggregateEdges(
			index,
			cut,
			pages(page('a', [edge('b', 'builds-on', 0.2, 'in')])),
			'builds-on'
		);
		expect(backwards[0]).toMatchObject({ from: 'b', to: 'a', directed: true });
	});
	it('skips bubbles whose page is not loaded', () => {
		expect(aggregateEdges(index, cutOf(index, []), new Map(), 'related')).toEqual([]);
	});
});

describe('topPerNode', () => {
	const e = (from: string, to: string, weight: number): MapEdge => ({
		key: `${from}|${to}`,
		type: 'related',
		from,
		to,
		directed: false,
		weight,
		confidence: 1,
		rolledUp: 0
	});
	it('keeps an edge when either end keeps it', () => {
		const edges = [e('x', 'a', 5), e('x', 'b', 4), e('x', 'c', 3), e('c', 'd', 1)];
		const kept = topPerNode(edges, 2).map((k) => k.key);
		// x keeps a and b; x–c is kept because c has room, and so is c–d
		expect(kept).toEqual(['x|a', 'x|b', 'x|c', 'c|d']);
	});
	it('drops an edge that neither end keeps', () => {
		const edges = [e('x', 'y', 9), e('x', 'z', 8), e('y', 'w', 7), e('x', 'w', 1)];
		// k = 1: x keeps y; y keeps x–y; z keeps x–z; w keeps y–w; x–w is nobody's strongest
		expect(topPerNode(edges, 1).map((k) => k.key)).toEqual(['x|y', 'x|z', 'y|w']);
	});
});

describe('ghostLinks', () => {
	it('links a bubble to where its other parent is drawn', () => {
		expect(ghostLinks(index, cutOf(index, ['a']))).toEqual([
			{ key: 'ghost|a2|b', from: 'a2', to: 'b' }
		]);
	});
	it('goes to the nearest drawn ancestor of the other parent and never to itself', () => {
		const links = ghostLinks(index, cutOf(index, ['a']));
		expect(links.every((l) => l.from !== l.to)).toBe(true);
		// the other parent b is collapsed: the link lands on b; once b is a hull it still does
		expect(ghostLinks(index, cutOf(index, ['a', 'b']))[0].to).toBe('b');
	});
});

describe('normaliseWeights', () => {
	it('scales to the strongest edge of the list', () => {
		const w = normaliseWeights([
			{ key: 'p', weight: 0.5 } as MapEdge,
			{ key: 'q', weight: 0.25 } as MapEdge
		]);
		expect(w.get('p')).toBe(1);
		expect(w.get('q')).toBe(0.5);
		expect(normaliseWeights([]).size).toBe(0);
	});
});
