import { error } from '@sveltejs/kit';
import { getDataSource } from '#lib/data/index.js';
import type { PageLoad } from './$types';

// Rendered in the browser from one authors shard (PLAN §11.2).
export const prerender = false;

export const load: PageLoad = async ({ fetch, params }) => {
	const author = await getDataSource(fetch).getAuthor(params.id);
	if (!author) error(404, `There is no author "${params.id}".`);
	return { author };
};
