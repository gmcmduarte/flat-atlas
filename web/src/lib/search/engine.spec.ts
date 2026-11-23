import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { SearchEngine, fold } from './engine';
import type { SearchIndex } from '../data/types';

const small: SearchIndex = {
	topics: [
		{ topic_id: 'sc', name: 'State complexity of operations', aliases: ['descriptional size'] },
		{ topic_id: 'fa', name: 'Finite automata', aliases: [] }
	],
	authors: [
		{ author_id: 'A1', name: 'Jacques Sakarovitch' },
		{ author_id: 'A2', name: 'Anna Müller' }
	],
	venues: [{ venue_id: 'V1', name: 'Developments in Language Theory', acronym: 'DLT' }],
	works: [
		{ work_id: 'W1', title: 'Elements of Automata Theory', year: 2009 },
		{ work_id: 'W2', title: 'State complexity of reversal', year: 2012 }
	]
};

describe('fold', () => {
	it('removes accents and case', () => expect(fold('Müller')).toBe('muller'));
});

describe('SearchEngine', () => {
	const engine = new SearchEngine(small);
	it('finds a topic by name words, prefix and alias', () => {
		expect(engine.search('state complexity').topics.map((t) => t.topic_id)).toEqual(['sc']);
		expect(engine.search('autom').topics.map((t) => t.topic_id)).toEqual(['fa']);
		expect(engine.search('descriptional').topics.map((t) => t.topic_id)).toEqual(['sc']);
	});
	it('groups results by kind', () => {
		const found = engine.search('state complexity');
		expect(found.works.map((w) => w.work_id)).toEqual(['W2']);
		expect(found.authors).toEqual([]);
	});
	it('ignores accents and tolerates a typo in a longer word', () => {
		expect(engine.search('muller').authors.map((a) => a.author_id)).toEqual(['A2']);
		expect(engine.search('Sakarovich').authors.map((a) => a.author_id)).toEqual(['A1']);
	});
	it('finds a venue by acronym', () => {
		expect(engine.search('dlt').venues.map((v) => v.venue_id)).toEqual(['V1']);
	});
	it('finds nothing for an empty or one-letter query', () => {
		expect(engine.search('  ').topics).toEqual([]);
		expect(engine.search('s').topics).toEqual([]);
	});
	it('falls back to any word when no result has all of them', () => {
		expect(engine.search('automata zzzzz').topics.map((t) => t.topic_id)).toEqual(['fa']);
	});
});

// The pilot data is git-ignored: this runs where `flatatlas export static` has been run.
const real = new URL('../../../static/data/search/index.json', import.meta.url);
describe.skipIf(!existsSync(real))('SearchEngine on the pilot data', () => {
	const engine = () => new SearchEngine(JSON.parse(readFileSync(real, 'utf8')) as SearchIndex);
	it('finds the topic "state complexity", a known author and a known paper', () => {
		const e = engine();
		expect(e.search('state complexity').topics[0]?.name).toMatch(/state complexity/i);
		expect(e.search('Sakarovitch').authors.length).toBeGreaterThan(0);
		expect(e.search('Holzer Kutrib').authors.length).toBeGreaterThan(0);
		expect(e.search('derivatives of regular expressions').works.length).toBeGreaterThan(0);
	});
});
