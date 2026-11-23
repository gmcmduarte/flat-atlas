import { describe, expect, it } from 'vitest';
import { OPTIONS, publicPageUrl, scrub, suggestUrl, type EntityType } from './suggest';

const entity = { type: 'paper' as const, id: 'WT3SYS5P77T', name: 'Shuffle & "words" @ Lyndon' };

function parse(url: string) {
	const u = new URL(url);
	return { u, p: u.searchParams };
}

describe('suggestUrl', () => {
	it('points at the issue form of the template, with the entity filled in', () => {
		const { u, p } = parse(
			suggestUrl({
				template: 'wrong-tag',
				entity,
				currentValue: 'Regular languages (confidence 96%)',
				pathname: '/flat-atlas/paper/WT3SYS5P77T',
				base: '/flat-atlas'
			})
		);
		expect(u.origin + u.pathname).toBe('https://github.com/gmcmduarte/flat-atlas/issues/new');
		expect(p.get('template')).toBe('wrong-tag.yml');
		expect(p.get('entity_id')).toBe('WT3SYS5P77T');
		expect(p.get('entity_name')).toBe(entity.name);
		expect(p.get('current_value')).toBe('Regular languages (confidence 96%)');
		expect(p.get('title')).toBe(`Wrong tag: ${entity.name}`);
		expect(p.get('page_url')).toBe('https://gmcmduarte.github.io/flat-atlas/paper/WT3SYS5P77T');
		// labels would need triage rights on the repository (GitHub answers 404 otherwise)
		expect(p.has('labels')).toBe(false);
	});

	it('keeps nothing private in the address', () => {
		const url = suggestUrl({
			template: 'other',
			entity: { type: 'topic', id: 'x', name: 'Topic' },
			currentValue:
				'mail me at someone@example.org, file:///Users/gui/data, http://localhost:4173/x',
			pathname: '/topic/x?focus=y#top',
			base: ''
		});
		const decoded = decodeURIComponent(url.replace(/\+/g, ' '));
		for (const bad of ['@', 'localhost', '/Users/', 'file://', 'focus=', '#top']) {
			expect(decoded).not.toContain(bad);
		}
		expect(parse(url).p.get('page_url')).toBe('https://gmcmduarte.github.io/flat-atlas/topic/x');
	});

	it('stays below the length GitHub accepts', () => {
		const url = suggestUrl({
			template: 'wrong-tag',
			entity: { type: 'paper', id: 'W1', name: 'N'.repeat(500) },
			currentValue: 'v '.repeat(2000),
			pathname: '/paper/W1',
			base: ''
		});
		expect(url.length).toBeLessThanOrEqual(1800);
		expect(parse(url).p.get('entity_id')).toBe('W1');
	});
});

describe('publicPageUrl', () => {
	it('removes the base path and any query or hash', () => {
		expect(publicPageUrl('/flat-atlas/venue/V1', '/flat-atlas')).toBe(
			'https://gmcmduarte.github.io/flat-atlas/venue/V1'
		);
		expect(publicPageUrl('/venue/V1?x=1#y', '')).toBe(
			'https://gmcmduarte.github.io/flat-atlas/venue/V1'
		);
	});
});

describe('scrub', () => {
	it('collapses white space and cuts long text', () => {
		expect(scrub('  a \n b  ', 10)).toBe('a b');
		expect(scrub('abcdefghij', 5)).toBe('abcd…');
	});
});

describe('OPTIONS', () => {
	it('offers every entity type a primary form that exists', () => {
		const primary: Record<EntityType, string> = {
			topic: 'wrong-tag',
			paper: 'wrong-tag',
			author: 'author-merge-split',
			venue: 'venue-fact'
		};
		for (const [type, expected] of Object.entries(primary)) {
			expect(OPTIONS[type as EntityType][0].template).toBe(expected);
		}
	});
});
