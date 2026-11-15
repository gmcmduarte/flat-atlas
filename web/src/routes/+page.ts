import { getDataSource } from '#lib/data/index.js';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
	const topics = await getDataSource(fetch).getTopics();
	return { topics };
};
