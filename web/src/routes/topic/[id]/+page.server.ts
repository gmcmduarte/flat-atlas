import { readFile } from 'node:fs/promises';
import { PUBLIC_DATA_DIR } from '$app/env/public';
import type { EntryGenerator } from './$types';

// Topic pages are prerendered for link previews and search engines: one per topic in the data
// folder. (This file has no `load`, so in the browser the page loads through `+page.ts`.)
export const entries: EntryGenerator = async () => {
	const dir = PUBLIC_DATA_DIR;
	const topics = JSON.parse(await readFile(`static/${dir}/topics.json`, 'utf8')) as {
		topic_id: string;
	}[];
	return topics.map((t) => ({ id: t.topic_id }));
};
