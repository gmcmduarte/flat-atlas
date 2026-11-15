import { readFile } from 'node:fs/promises';
import { describe, expect, it } from 'vitest';
import { StaticDataSource, shardOf } from './StaticDataSource';

const ROOT = new URL('../../../static/data-fixture/', import.meta.url);
const BASE = 'https://example.test/flat-atlas/data-fixture';

/** A `fetch` that serves the fixture folder from disk and answers 404 for anything else. */
const fakeFetch: typeof fetch = async (input) => {
	const url = String(input);
	if (!url.startsWith(`${BASE}/`)) return new Response('wrong base', { status: 500 });
	try {
		const body = await readFile(new URL(url.slice(BASE.length + 1), ROOT), 'utf8');
		return new Response(body, { status: 200 });
	} catch {
		return new Response('not found', { status: 404 });
	}
};

const source = () => new StaticDataSource(fakeFetch, BASE);

describe('shardOf', () => {
	it('is the first two hex characters of the SHA-256 of the id', async () => {
		// Same values as the fixture files: works/1e.json holds WFIXTUREAAA.
		expect(await shardOf('WFIXTUREAAA')).toBe('1e');
		expect(await shardOf('AFIXTUREAAA')).toBe('3f');
	});
});

describe('StaticDataSource', () => {
	it('lists the fixture topics', async () => {
		const topics = await source().getTopics();
		expect(topics).toHaveLength(5);
		expect(topics.filter((t) => t.level === 0).map((t) => t.topic_id)).toEqual([
			'formal-languages',
			'automata-theory'
		]);
	});

	it('loads a topic page with two lateral edge types', async () => {
		const page = await source().getTopic('finite-automata');
		expect(page?.topic.name).toBe('Finite automata');
		expect(page?.parents.map((p) => p.topic_id)).toEqual(['automata-theory', 'formal-languages']);
		expect(page?.edges.related.length).toBeGreaterThan(0);
		expect(page?.edges['builds-on'].length).toBeGreaterThan(0);
	});

	it('finds works, authors and the venue through their shards', async () => {
		const s = source();
		const work = await s.getWork('WFIXTUREAAA');
		expect(work?.tags[0].confidence).toBeGreaterThan(0);
		expect(work?.tags[0].provenance.method).toBe('fixture');
		expect((await s.getAuthor('AFIXTUREAAA'))?.display_name).toBe('Ada Fixture');
		expect((await s.getVenue('VFIXTUREAAA'))?.acronym).toBe('FIXCONF');
	});

	it('returns null for unknown ids, in an existing shard or a missing one', async () => {
		const s = source();
		expect(await s.getTopic('no-such-topic')).toBeNull();
		expect(await s.getWork('WNOSUCHWORK')).toBeNull();
		expect(await s.getVenue('VNOSUCHVENU')).toBeNull();
	});

	it('searches topic names and loads the map', async () => {
		const s = source();
		expect((await s.search('automata')).topics.map((t) => t.topic_id)).toContain('finite-automata');
		expect((await s.search('   ')).topics).toEqual([]);
		expect((await s.getMap()).nodes).toHaveLength(5);
	});

	it('reports a failing host instead of returning data', async () => {
		const broken = new StaticDataSource(async () => new Response('boom', { status: 500 }), BASE);
		await expect(broken.getTopics()).rejects.toThrow('HTTP 500');
	});

	it('rejects an HTML page served with status 200 for a JSON file', async () => {
		const html = new StaticDataSource(async () => new Response('<html></html>'), BASE);
		await expect(html.getTopics()).rejects.toThrow('not JSON');
	});
});
