import { error } from '@sveltejs/kit';
import { getDataSource } from '#lib/data/index.js';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, params }) => {
	const venue = await getDataSource(fetch).getVenue(params.id);
	if (!venue) error(404, `There is no venue "${params.id}".`);
	return { venue };
};
