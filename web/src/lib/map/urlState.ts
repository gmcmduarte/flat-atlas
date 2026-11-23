import type { MapIndex } from './model';

/** The query parameter that keeps the map state: the topic in focus (`?focus=<topic_id>`). */
export const FOCUS_PARAM = 'focus';

/**
 * The focus topic of a URL's query string, or null when it is absent or not on the map. The
 * home page is prerendered, so this is only called in the browser.
 */
export function readFocus(search: string, index: MapIndex): string | null {
	const value = new URLSearchParams(search).get(FOCUS_PARAM);
	return value && index.topics.has(value) ? value : null;
}

/** `url` with the focus set (or removed); everything else in the URL is kept. */
export function withFocus(url: { href: string }, focus: string | null): URL {
	const next = new URL(url.href);
	if (focus) next.searchParams.set(FOCUS_PARAM, focus);
	else next.searchParams.delete(FOCUS_PARAM);
	return next;
}
