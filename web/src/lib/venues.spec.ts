import { describe, expect, it } from 'vitest';
import type { DataVenue } from '#lib/data/types.js';
import { coverageSentence, formatDate, joinList, venueSeries } from './venues';

const v = (
	id: string,
	acronym: string,
	first_year: number,
	last_year: number | null,
	successor_of: string[] = []
): DataVenue => ({ venue_id: id, acronym, name: acronym, first_year, last_year, successor_of });

// The shape of the pilot release (v2026.11.0): five records, three series.
const pilot = [
	v('V1', 'DLT', 1993, null),
	v('V2', 'DCAGRS', 2001, 2001),
	v('V3', 'DCFS', 2002, null, ['V2']),
	v('V4', 'CIAA', 2000, null, ['V5']),
	v('V5', 'WIA', 1996, 1999)
];

describe('venueSeries', () => {
	it('counts series, not records, and orders them by their first year', () => {
		const s = venueSeries(pilot);
		expect(s.map((x) => x.current.acronym)).toEqual(['DLT', 'CIAA', 'DCFS']);
		expect(s[1].predecessors.map((p) => p.acronym)).toEqual(['WIA']);
		expect(s[1].firstYear).toBe(1996);
		expect(s[2].predecessors.map((p) => p.acronym)).toEqual(['DCAGRS']);
	});

	it('follows a chain of renames', () => {
		const s = venueSeries([
			v('A', 'A', 1990, 1995),
			v('B', 'B', 1996, 2000, ['A']),
			v('C', 'C', 2001, null, ['B'])
		]);
		expect(s).toHaveLength(1);
		expect(s[0].predecessors.map((p) => p.acronym)).toEqual(['A', 'B']);
	});

	it('does not loop on a cycle and ignores unknown ids', () => {
		expect(venueSeries([v('A', 'A', 1, null, ['B']), v('B', 'B', 2, null, ['A'])])).toHaveLength(2);
		expect(venueSeries([v('A', 'A', 1, null, ['ZZ'])])[0].predecessors).toEqual([]);
	});

	it('handles the fixture (one venue) and an empty list', () => {
		expect(venueSeries([v('F', 'FIXCONF', 2001, 2023)])).toHaveLength(1);
		expect(venueSeries([])).toEqual([]);
	});
});

describe('coverageSentence', () => {
	it('is written from the release data', () => {
		expect(coverageSentence({ works: 2333, venues: pilot })).toBe(
			'2,333 papers from 3 conference series (DLT, CIAA and DCFS, with their predecessors WIA and DCAGRS)'
		);
	});
	it('has no predecessor clause when there are none', () => {
		expect(coverageSentence({ works: 12, venues: [v('F', 'FIXCONF', 2001, 2023)] })).toBe(
			'12 papers from 1 conference series (FIXCONF)'
		);
	});
});

describe('helpers', () => {
	it('joins lists and formats dates', () => {
		expect(joinList([])).toBe('');
		expect(joinList(['a'])).toBe('a');
		expect(joinList(['a', 'b'])).toBe('a and b');
		expect(joinList(['a', 'b', 'c'])).toBe('a, b and c');
		expect(formatDate('2026-11-20')).toBe('20 November 2026');
		expect(formatDate('garbage')).toBe('garbage');
	});
});
