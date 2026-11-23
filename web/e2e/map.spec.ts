import { expect, test, type Page } from '@playwright/test';

// The topic map of P1-11 on the fixture data: 2 top-level topics (Formal languages, Automata
// theory) with 3 subtopics between them. Counts are read from the DOM: the topic tree mirrors every
// bubble the canvas draws, and the canvas root carries data-node-count and data-edge-count.

function watch(page: Page) {
	const errors: string[] = [];
	page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
	page.on('pageerror', (e) => errors.push(e.message));
	return errors;
}

async function ready(page: Page) {
	await expect(page.locator('.map[data-status="ready"][data-fitted="true"]')).toBeAttached();
}

/** Where a level-0 bubble is on the canvas right after the first fit (y points up in the layout). */
async function rootPoint(page: Page, id: string) {
	const layout = (await (await page.request.get('/data-fixture/map.json')).json()) as {
		nodes: { topic_id: string; level: number; x: number; y: number; r: number }[];
	};
	const roots = layout.nodes.filter((n) => n.level === 0);
	const x0 = Math.min(...roots.map((n) => n.x - n.r));
	const x1 = Math.max(...roots.map((n) => n.x + n.r));
	const y0 = Math.min(...roots.map((n) => n.y - n.r));
	const y1 = Math.max(...roots.map((n) => n.y + n.r));
	const box = (await page.locator('.map').boundingBox())!;
	const scale = Math.min((box.width * 0.8) / (x1 - x0), (box.height * 0.8) / (y1 - y0));
	const node = layout.nodes.find((n) => n.topic_id === id)!;
	return {
		x: box.x + box.width / 2 + (node.x - (x0 + x1) / 2) * scale,
		y: box.y + box.height / 2 - (node.y - (y0 + y1) / 2) * scale
	};
}

const tree = (page: Page) => page.getByRole('tree', { name: 'Topics on the map' });

test('the map shows the top-level bubbles, opens one on click and switches edge types', async ({
	page
}) => {
	const errors = watch(page);
	await page.goto('/');
	await ready(page);

	await expect(tree(page).getByRole('treeitem')).toHaveCount(2);
	await expect(page.locator('.map')).toHaveAttribute('data-node-count', '2');
	// the default edge type is "related": one link between the two top-level topics
	await expect(page.getByRole('radio', { name: 'Related' })).toBeChecked();
	await expect(page.locator('.map')).toHaveAttribute('data-edge-count', '1');

	// a click on the canvas opens the bubble in place: its subtopics appear, the URL keeps the state
	const p = await rootPoint(page, 'automata-theory');
	await page.mouse.click(p.x, p.y);
	await expect(tree(page).getByRole('treeitem')).toHaveCount(4);
	await expect(page).toHaveURL(/\?focus=automata-theory$/);
	await expect(tree(page).getByRole('treeitem', { name: /Finite automata/ })).toBeAttached();
	// a stored edge to a topic inside the closed "Formal languages" is rolled up to that bubble
	await expect(page.locator('.map')).toHaveAttribute('data-edge-count', '2');

	// each edge type has its own legend; an empty one says so
	await page.getByRole('radio', { name: 'Shared community' }).check();
	await expect(page.locator('.map')).toHaveAttribute('data-edge-count', '0');
	await expect(page.getByText('No shared community links among the bubbles shown')).toBeVisible();
	await page.getByRole('radio', { name: 'Builds on' }).check();
	await expect(page.locator('.map')).toHaveAttribute('data-edge-count', '2');
	await expect(page.locator('.legend')).toContainText('pointing at the topic that is built on');

	// Back closes it again
	await page.getByRole('button', { name: /Back/ }).click();
	await expect(tree(page).getByRole('treeitem')).toHaveCount(2);

	expect(errors).toEqual([]);
});

test('the topic tree is a keyboard interface to the map', async ({ page }) => {
	const errors = watch(page);
	await page.goto('/');
	await ready(page);

	await page.getByRole('treeitem', { name: /Formal languages/ }).focus();
	await page.keyboard.press('ArrowRight'); // opens
	await expect(page.getByRole('treeitem', { name: /Formal languages/ })).toHaveAttribute(
		'aria-expanded',
		'true'
	);
	await page.keyboard.press('ArrowRight'); // first child
	await expect(page.getByRole('treeitem', { name: /Regular languages/ })).toBeFocused();
	await page.keyboard.press('ArrowLeft'); // back to the parent
	await expect(page.getByRole('treeitem', { name: /Formal languages/ })).toBeFocused();
	await page.keyboard.press('ArrowLeft'); // closes
	await expect(tree(page).getByRole('treeitem')).toHaveCount(2);

	await page.keyboard.press('Enter'); // opens the topic page
	await expect(page).toHaveURL(/\/topic\/formal-languages$/);
	expect(errors).toEqual([]);
});

test('the list view shows the same state with a link to every topic page', async ({ page }) => {
	const errors = watch(page);
	await page.goto('/?focus=automata-theory');
	await ready(page);
	await expect(tree(page).getByRole('treeitem')).toHaveCount(4);

	await page.getByRole('button', { name: 'List' }).click();
	const rows = tree(page).getByRole('treeitem');
	await expect(rows).toHaveCount(4);
	await expect(rows.first()).toBeVisible();
	await expect(
		rows.filter({ hasText: 'Finite automata' }).getByRole('link', { name: /Open topic page/ })
	).toHaveAttribute('href', /\/topic\/finite-automata$/);

	// a row opens and closes a topic; the map keeps the state when switched back
	await rows.filter({ hasText: 'Formal languages' }).click();
	await expect(tree(page).getByRole('treeitem')).toHaveCount(5);
	await page.getByRole('button', { name: 'Map' }).click();
	await expect(page.locator('.map')).toBeVisible();
	await expect(tree(page).getByRole('treeitem')).toHaveCount(5);
	expect(errors).toEqual([]);
});

test('search focuses the map on the home page and the URL restores the view', async ({ page }) => {
	const errors = watch(page);
	await page.goto('/');
	await ready(page);

	await page.getByRole('combobox', { name: /search/i }).fill('finite automata');
	await page.getByRole('option', { name: 'Finite automata', exact: true }).click();
	// still on the home page, with the topic on the map
	await expect(page).toHaveURL(/\/\?focus=finite-automata$/);
	await expect(page.getByRole('treeitem', { name: /Finite automata/ })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await expect(page.getByRole('link', { name: 'Open topic page' }).first()).toHaveAttribute(
		'href',
		/\/topic\/finite-automata$/
	);

	await page.reload();
	await ready(page);
	await expect(page.getByRole('treeitem', { name: /Finite automata/ })).toBeAttached();
	await expect(tree(page).getByRole('treeitem')).toHaveCount(4);
	expect(errors).toEqual([]);
});
