import { getDataSource } from '#lib/data/index.js';
import type { LayoutLoad } from './$types';

// Pages are prerendered where their data is known at build time (the home page, topic and venue
// pages, /about). Any other URL, such as a paper, an author or the search page, is served by the
// `404.html` fallback and rendered in the browser (PLAN §11.2).
export const prerender = true;

// What every page may need: the topic list (names for breadcrumbs and chips) and the release
// the data comes from (footer).
export const load: LayoutLoad = async ({ fetch }) => {
	const source = getDataSource(fetch);
	const [topics, meta] = await Promise.all([source.getTopics(), source.getMeta()]);
	return { topics, meta };
};
