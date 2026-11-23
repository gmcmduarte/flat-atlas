import { readdir } from 'node:fs/promises';
import { PUBLIC_DATA_DIR } from '$app/env/public';
import type { EntryGenerator } from './$types';

// Venue pages are prerendered: one per file in the data folder's `venue/`.
// (No `load` here, so in the browser the page loads through `+page.ts`.)
export const entries: EntryGenerator = async () => {
	const files = await readdir(`static/${PUBLIC_DATA_DIR}/venue`);
	return files.filter((f) => f.endsWith('.json')).map((f) => ({ id: f.slice(0, -'.json'.length) }));
};
