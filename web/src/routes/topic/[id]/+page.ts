import { error } from '@sveltejs/kit';
import { getDataSource } from '#lib/data/index.js';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, params }) => {
	const page = await getDataSource(fetch).getTopic(params.id);
	if (!page) error(404, `There is no topic "${params.id}".`);
	return { page };
};
