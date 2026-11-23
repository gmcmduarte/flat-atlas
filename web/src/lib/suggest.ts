/**
 * "Suggest a change" links (PLAN §15.6): a pre-filled GitHub issue-form URL.
 *
 * Only public values go into the URL: the entity's id and name, a short description of what the
 * page shows, and the public address of the page. Nothing from the visitor's browser (no query
 * string, no hash, no local address) and no email address ever enters it; `scrub` removes what
 * looks like one as a second line of defence.
 */
import { REPO, SITE_URL } from './site';

export type Template =
	'wrong-tag' | 'missing-paper' | 'author-merge-split' | 'new-topic' | 'venue-fact' | 'other';

export type EntityType = 'topic' | 'paper' | 'author' | 'venue';

export interface SuggestEntity {
	type: EntityType;
	id: string;
	name: string;
}

/** The forms offered on each kind of page: the first is the primary one. */
export const OPTIONS: Record<EntityType, { template: Template; label: string }[]> = {
	topic: [
		{ template: 'wrong-tag', label: 'A paper is listed under the wrong topic, or one is missing' },
		{ template: 'new-topic', label: 'Propose a new topic or a change to this one' },
		{ template: 'other', label: 'Something else' }
	],
	paper: [
		{ template: 'wrong-tag', label: 'A topic of this paper is wrong or missing' },
		{ template: 'missing-paper', label: 'Another paper is missing from the atlas' },
		{ template: 'other', label: 'Something else' }
	],
	author: [
		{
			template: 'author-merge-split',
			label: 'Two author pages are one person, or this one mixes people'
		},
		{ template: 'other', label: 'Something else' }
	],
	venue: [
		{
			template: 'venue-fact',
			label: 'A fact about this venue is wrong (for example the acceptance rate)'
		},
		{ template: 'missing-paper', label: 'A paper of this venue is missing' },
		{ template: 'other', label: 'Something else' }
	]
};

const TITLE_PREFIX: Record<Template, string> = {
	'wrong-tag': 'Wrong tag: ',
	'missing-paper': 'Missing paper: ',
	'author-merge-split': 'Authors: ',
	'new-topic': 'New topic: ',
	'venue-fact': 'Venue fact: ',
	other: 'Suggestion: '
};

const MAX_URL = 1800;
const MAX_TITLE = 100;
const MAX_NAME = 200;
const MAX_VALUE = 600;

/** Collapse white space, drop what looks like an email address or a local path, cut to `max`. */
export function scrub(text: string, max: number): string {
	let t = text
		.replace(/\S+@\S+\.\S+/g, '[removed]')
		.replace(/(?:file:\/\/|\/Users\/|\/home\/|[A-Za-z]:\\)\S*/g, '[removed]')
		.replace(/\blocalhost\S*/gi, '[removed]')
		.replace(/\s+/g, ' ')
		.trim();
	if (t.length > max) t = `${t.slice(0, max - 1).trimEnd()}…`;
	return t;
}

/**
 * The public address of the page being viewed: `SITE_URL` plus the path below the base the
 * site is served under. No query string and no hash, whatever the visitor's address bar shows.
 */
export function publicPageUrl(pathname: string, base: string): string {
	let path = pathname.split(/[?#]/)[0] ?? '/';
	if (base && (path === base || path.startsWith(`${base}/`))) path = path.slice(base.length);
	if (!path.startsWith('/')) path = `/${path}`;
	return `${SITE_URL}${path}`;
}

export interface SuggestInput {
	template: Template;
	entity: SuggestEntity;
	/** A short, public description of what the page shows now (topics and confidence, counts). */
	currentValue?: string;
	/** `location.pathname` of the page. */
	pathname: string;
	/** The base path the site is served under (`SITE_BASE`); removed from the pathname. */
	base: string;
}

export function suggestUrl(input: SuggestInput): string {
	const { template, entity } = input;
	const build = (currentValue: string) => {
		const params = new URLSearchParams();
		params.set('template', `${template}.yml`);
		params.set('title', scrub(`${TITLE_PREFIX[template]}${entity.name}`, MAX_TITLE));
		params.set('entity_id', scrub(entity.id, 80));
		params.set('entity_name', scrub(entity.name, MAX_NAME));
		if (currentValue) params.set('current_value', currentValue);
		params.set('page_url', publicPageUrl(input.pathname, input.base));
		return `https://github.com/${REPO}/issues/new?${params.toString()}`;
	};
	let value = scrub(input.currentValue ?? '', MAX_VALUE);
	let url = build(value);
	// GitHub answers 414 above its limit: shorten the one free-text value, then drop it.
	while (url.length > MAX_URL && value.length > 0) {
		value = value.length > 120 ? scrub(value, Math.floor(value.length / 2)) : '';
		url = build(value);
	}
	return url;
}
