import { error } from '@sveltejs/kit';
import { getDataSource } from '#lib/data/index.js';
import type { PageLoad } from './$types';

// Paper pages are rendered in the browser from one works shard (PLAN §11.2): no HTML per paper.
export const prerender = false;

export const load: PageLoad = async ({ fetch, params }) => {
	const work = await getDataSource(fetch).getWork(params.id);
	if (!work) error(404, `There is no paper "${params.id}".`);
	return { work };
};
