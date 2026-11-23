import { expect, test } from '@playwright/test';

// The browsing path of P1-10: search a topic, open it, open a child, open a paper, open an author.
// Runs on the fixture data; no console errors are allowed on the way.
test('search a topic, open a child, a paper and an author', async ({ page }) => {
	const errors: string[] = [];
	page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
	page.on('pageerror', (e) => errors.push(e.message));

	// from a page without the map: on the home page the same choice focuses the map (map.spec.ts)
	await page.goto('/about');
	await page.getByRole('combobox', { name: /search/i }).fill('formal languages');
	await page.getByRole('option', { name: 'Formal languages', exact: true }).click();

	await expect(page).toHaveURL(/\/topic\/formal-languages$/);
	await expect(page.getByRole('heading', { level: 1, name: 'Formal languages' })).toBeVisible();

	await page
		.getByRole('list', { name: 'Subtopics of Formal languages' })
		.getByRole('link', { name: 'Regular languages' })
		.click();
	await expect(page).toHaveURL(/\/topic\/regular-languages$/);
	await expect(page.getByRole('heading', { level: 1, name: 'Regular languages' })).toBeVisible();

	// the first paper of the list (a client-rendered page, served by the 404.html fallback)
	await page
		.getByRole('list', { name: 'Papers on Regular languages' })
		.getByRole('link')
		.first()
		.click();
	await expect(page).toHaveURL(/\/paper\/W/);
	await expect(page.getByRole('heading', { level: 2, name: 'Topics' })).toBeVisible();
	await expect(page.getByText(/Confidence \d+%/).first()).toBeVisible();

	await page.getByRole('list', { name: 'Authors' }).getByRole('link').first().click();
	await expect(page).toHaveURL(/\/author\/A/);
	await expect(page.getByRole('heading', { level: 2, name: /^Papers \(/ })).toBeVisible();

	expect(errors).toEqual([]);
});
