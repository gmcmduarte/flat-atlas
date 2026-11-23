import { describe, expect, it } from 'vitest';
import { sortPapers, type Sortable } from './sortPapers';

const p = (
	work_id: string,
	year: number,
	confidence: number,
	cited_by_count: number,
	low_confidence = false
): Sortable => ({ work_id, year, confidence, cited_by_count, low_confidence });

const papers = [
	p('A', 2000, 0.9, 10),
	p('B', 2020, 0.6, 100),
	p('C', 2010, 0.95, 0),
	p('W', 2021, 0.27, 500, true)
];

const ids = (list: Sortable[]) => list.map((x) => x.work_id).join('');

describe('sortPapers', () => {
	it('relevance is confidence times log citations', () => {
		expect(ids(sortPapers(papers, 'relevance'))).toBe('BACW');
	});
	it('most cited, newest and oldest first', () => {
		expect(ids(sortPapers(papers, 'cited'))).toBe('BACW');
		expect(ids(sortPapers(papers, 'newest'))).toBe('BCAW');
		expect(ids(sortPapers(papers, 'oldest'))).toBe('ACBW');
	});
	it('weak matches stay after the normal papers whatever the order', () => {
		for (const key of ['relevance', 'cited', 'newest', 'oldest'] as const) {
			expect(sortPapers(papers, key).at(-1)?.work_id).toBe('W');
		}
	});
	it('does not change its input and breaks ties by id', () => {
		const same = [p('Z', 2000, 0.5, 1), p('Y', 2000, 0.5, 1)];
		expect(ids(sortPapers(same, 'newest'))).toBe('YZ');
		expect(ids(same)).toBe('ZY');
	});
});
