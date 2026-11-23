import { describe, expect, it } from 'vitest';
import { band, explainProvenance, isWeakMatch } from './provenance';
import type { Provenance } from './data/types';

const prov = (signals: Record<string, number>, flags: string[] = []): Provenance => ({
	method: 'fusion',
	signals,
	tagger_version: 'tagger-3',
	taxonomy_version: '1',
	flags
});

describe('explainProvenance', () => {
	it('names the strongest signals in plain words, best first, at most three', () => {
		const text = explainProvenance(
			prov({ lex_title: 1, emb_desc: 0.97, emb_seed: 0.9, lex_abstract: 0.6, venue_prior: 0.01 }),
			0.93
		);
		expect(text).toContain('Confidence 93%.');
		expect(text).toContain(
			'topic words in the title (100%); similarity to the topic description (97%); ' +
				"similarity to the topic's example papers (90%)"
		);
		expect(text).not.toContain('abstract');
		expect(text).not.toContain('venue');
		expect(text).toContain('Method: learned combination of signals (fusion, tagger-3).');
	});

	it('says so when no signal is strong', () => {
		expect(explainProvenance(prov({ lex_title: 0.1, emb_desc: 0.3 }), 0.4)).toContain(
			'No single signal is strong'
		);
	});

	it('calls a low-confidence tag a weak match', () => {
		const p = prov({ emb_desc: 0.31 }, ['low_confidence']);
		expect(isWeakMatch(p)).toBe(true);
		expect(explainProvenance(p, 0.27)).toContain('Weak match');
	});

	it('ignores signals it has no words for', () => {
		expect(explainProvenance(prov({ mystery: 0.99 }), 0.9)).toContain('No single signal');
	});
});

describe('band', () => {
	it('splits at 0.8 and 0.5', () => {
		expect([0.95, 0.8, 0.79, 0.5, 0.49].map(band)).toEqual([
			'high',
			'high',
			'medium',
			'medium',
			'low'
		]);
	});
});
