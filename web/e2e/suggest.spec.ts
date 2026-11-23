import { expect, test } from '@playwright/test';

// P1-12: every topic, paper, author and venue page ends with "Suggest a change"; the first link
// is a pre-filled GitHub issue-form URL for the right template, with the entity's id and only
// public values in it. Fixture data (ids below); the pages are the built site.
const CASES = [
	{
		type: 'topic',
		path: '/topic/regular-languages',
		id: 'regular-languages',
		template: 'wrong-tag.yml'
	},
	{ type: 'paper', path: '/paper/WFIXTUREAAG', id: 'WFIXTUREAAG', template: 'wrong-tag.yml' },
	{
		type: 'author',
		path: '/author/AFIXTUREAAA',
		id: 'AFIXTUREAAA',
		template: 'author-merge-split.yml'
	},
	{ type: 'venue', path: '/venue/VFIXTUREAAA', id: 'VFIXTUREAAA', template: 'venue-fact.yml' }
] as const;

for (const c of CASES) {
	test(`the suggest link on a ${c.type} page names the form and the ${c.type} id`, async ({
		page
	}) => {
		const errors: string[] = [];
		page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
		page.on('pageerror', (e) => errors.push(e.message));

		await page.goto(`${c.path}?focus=private&q=secret#top`);
		await expect(page.getByRole('heading', { level: 2, name: 'Suggest a change' })).toBeVisible();

		const href = await page.locator('a[data-suggest="primary"]').getAttribute('href');
		expect(href).not.toBeNull();
		const url = new URL(href!);
		expect(url.origin + url.pathname).toBe('https://github.com/gmcmduarte/flat-atlas/issues/new');
		expect(url.searchParams.get('template')).toBe(c.template);
		expect(url.searchParams.get('entity_id')).toBe(c.id);
		expect(url.searchParams.get('entity_name')).toBeTruthy();
		// the public address of the page, without the visitor's query string or hash
		expect(url.searchParams.get('page_url')).toBe(
			`https://gmcmduarte.github.io/flat-atlas${c.path}`
		);

		// every link of the section opens a form that exists, and nothing private is in any of them
		const hrefs = await page
			.locator('section.suggest a')
			.evaluateAll((as) => as.map((a) => (a as HTMLAnchorElement).href));
		expect(hrefs.length).toBeGreaterThanOrEqual(2);
		for (const h of hrefs) {
			const decoded = decodeURIComponent(h.replace(/\+/g, ' '));
			for (const bad of ['localhost', '127.0.0.1', '/Users/', 'file://', '@', 'secret', 'focus=']) {
				expect(decoded, `${bad} in ${h}`).not.toContain(bad);
			}
			expect(h.length).toBeLessThanOrEqual(1800);
		}
		expect(errors).toEqual([]);
	});
}
