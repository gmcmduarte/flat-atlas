import { describe, expect, it } from 'vitest';
import { ancestorPaths } from './topics';
import type { Topic } from './data/types';

const t = (topic_id: string, parents: string[] = []): Topic => ({
	topic_id,
	name: topic_id.toUpperCase(),
	description: '',
	level: parents.length ? 1 : 0,
	parents,
	children: [],
	paper_count: 0,
	volume: 0,
	n_low_confidence: 0
});
const names = (paths: Topic[][]) => paths.map((path) => path.map((x) => x.topic_id).join('>'));

describe('ancestorPaths', () => {
	it('is empty for a root and for an unknown topic', () => {
		const topics = [t('a')];
		expect(ancestorPaths(topics, 'a')).toEqual([]);
		expect(ancestorPaths(topics, 'zzz')).toEqual([]);
	});
	it('gives one path per route through the parents', () => {
		// d has parents b and c; b and c both sit under a; c also under x (a second root)
		const topics = [t('a'), t('x'), t('b', ['a']), t('c', ['a', 'x']), t('d', ['b', 'c'])];
		expect(names(ancestorPaths(topics, 'd'))).toEqual(['a>b', 'a>c', 'x>c']);
		expect(names(ancestorPaths(topics, 'b'))).toEqual(['a']);
	});
	it('cuts a cycle instead of looping', () => {
		const topics = [t('a', ['b']), t('b', ['a'])];
		expect(() => ancestorPaths(topics, 'a')).not.toThrow();
	});
});
