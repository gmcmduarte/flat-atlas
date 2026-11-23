import { expect, test, type Page } from '@playwright/test';

// P1-12: the content pages, the release banner and the 404 page, on the fixture data. Nothing may
// be fetched from another origin and the console must stay clean.

function watch(page: Page) {
	const errors: string[] = [];
	const foreign: string[] = [];
	page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
	page.on('pageerror', (e) => errors.push(e.message));
	page.on('request', (r) => {
		const u = new URL(r.url());
		if (u.origin !== 'http://localhost:4173' && u.protocol.startsWith('http'))
			foreign.push(r.url());
	});
	return { errors, foreign };
}

for (const [path, h1] of [
	['/about', 'About'],
	['/methods', 'Methods'],
	['/sources', 'Sources'],
	['/cite', 'Cite']
] as const) {
	test(`${path} renders with the release banner and no outside requests`, async ({ page }) => {
		const seen = watch(page);
		await page.goto(path);
		await expect(page.getByRole('heading', { level: 1, name: h1, exact: true })).toBeVisible();
		await expect(page.getByRole('complementary', { name: 'About this data' })).toContainText(
			'Fixture data'
		);
		await expect(
			page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Methods' })
		).toBeVisible();
		expect(seen.errors).toEqual([]);
		expect(seen.foreign).toEqual([]);
	});
}

test('Sources carries the literal Semantic Scholar attribution and the licences', async ({
	page
}) => {
	await page.goto('/sources');
	const main = page.getByRole('main');
	await expect(main).toContainText('This site uses data from Semantic Scholar');
	await expect(main).toContainText('Kinney');
	for (const licence of ['CC0 1.0', 'ODC-BY 1.0', 'CC BY 4.0', 'MIT']) {
		await expect(main).toContainText(licence);
	}
	await expect(page.getByRole('contentinfo')).toContainText('Semantic Scholar');
});

test('Methods states what is shipped, what is off, and the known limits', async ({ page }) => {
	await page.goto('/methods');
	const main = page.getByRole('main');
	await expect(main).toContainText('average of five such models');
	await expect(main).toContainText('What is switched off, and why');
	await expect(main).toContainText('local open language model');
	await expect(main).toContainText('drafted by an AI assistant');
	await expect(main).toContainText('cannot be compared across kinds');
	await expect(main.getByRole('heading', { level: 2, name: 'Known limits' })).toBeVisible();
	// the limits state the weak number, not only the good ones
	await expect(main).toContainText('Subtopic recall is 62 %');
});

test('Cite shows the Zenodo DOI and says what the archive holds', async ({ page }) => {
	await page.goto('/cite');
	const main = page.getByRole('main');
	await expect(main.getByRole('link', { name: 'doi:10.5281/zenodo.24461535' })).toHaveAttribute(
		'href',
		'https://doi.org/10.5281/zenodo.24461535'
	);
	await expect(main.getByRole('link', { name: 'doi:10.5281/zenodo.24461534' })).toBeVisible();
	await expect(main).toContainText('not the data files');
	await expect(page.locator('pre')).toContainText('doi          = {10.5281/zenodo.24461535}');
});

test('an address that does not exist shows the 404 page', async ({ page }) => {
	const seen = watch(page);
	await page.goto('/no-such-page');
	await expect(page.getByRole('heading', { level: 1, name: 'Not found' })).toBeVisible();
	await expect(page.getByRole('link', { name: /start from the top-level topics/ })).toBeVisible();
	// the 404 itself is an expected "failed" resource, not a script error
	expect(seen.foreign).toEqual([]);
});

test('the head carries a public canonical address and a share image that exists', async ({
	page,
	request
}) => {
	await page.goto('/about');
	await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
		'href',
		'https://gmcmduarte.github.io/flat-atlas/about'
	);
	await expect(page.locator('meta[property="og:image"]')).toHaveAttribute(
		'content',
		'https://gmcmduarte.github.io/flat-atlas/og.png'
	);
	for (const file of ['/og.png', '/favicon.svg', '/apple-touch-icon.png']) {
		const res = await request.get(file);
		expect(res.ok(), file).toBe(true);
	}
});
