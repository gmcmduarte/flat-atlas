import MiniSearch from 'minisearch';
import type { SearchIndex, SearchResults } from '../data/types';
import { MIN_QUERY } from './limits';

/** Lower case, accents removed: "Müller" is found by "muller" and the other way round. */
export function fold(text: string): string {
	return text
		.normalize('NFD')
		.replace(/\p{Diacritic}/gu, '')
		.toLowerCase();
}

/** Fuzzy matching only for longer words, so short ones do not match unrelated ones. */
const fuzzy = (term: string) => (term.length >= 5 ? 0.15 : false);

function build<D extends object>(
	fields: string[],
	idField: string,
	docs: D[],
	boost: Record<string, number>
) {
	const index = new MiniSearch<D>({
		fields,
		storeFields: [],
		idField,
		processTerm: (term) => fold(term),
		searchOptions: { prefix: true, fuzzy, boost }
	});
	index.addAll(docs);
	return index;
}

/** The ids of the best matches of `query`: every word must match; if none does, any word may. */
function ids<D extends object>(index: MiniSearch<D>, query: string, limit: number): string[] {
	let found = index.search(query, { combineWith: 'AND' });
	if (found.length === 0 && /\s/.test(query.trim())) {
		found = index.search(query, { combineWith: 'OR' });
	}
	return found.slice(0, limit).map((r) => String(r.id));
}

/**
 * The client-side search of the static stage (PLAN §11.2): four small MiniSearch indexes built from
 * `search/index.json`, one per kind, so results come back grouped and a title word never
 * outranks a topic name. Built once, on first use (the page loads this module lazily).
 */
export class SearchEngine {
	private readonly topics;
	private readonly authors;
	private readonly venues;
	private readonly works;
	private readonly source: SearchIndex;

	constructor(source: SearchIndex) {
		this.source = source;
		this.topics = build(
			['name', 'aliases'],
			'topic_id',
			source.topics.map((t) => ({
				topic_id: t.topic_id,
				name: t.name,
				aliases: t.aliases.join(' ')
			})),
			{ name: 3, aliases: 2 }
		);
		this.authors = build(['name'], 'author_id', source.authors, {});
		this.venues = build(['acronym', 'name'], 'venue_id', source.venues, { acronym: 3 });
		this.works = build(['title'], 'work_id', source.works, {});
	}

	/** Up to `limit` results per group. An empty or one-letter query finds nothing. */
	search(query: string, limit = 10): SearchResults {
		const q = query.trim();
		if (q.length < MIN_QUERY) return { topics: [], authors: [], venues: [], works: [] };
		const pick = <T>(found: string[], all: T[], key: (item: T) => string): T[] => {
			const byId = new Map(all.map((item) => [key(item), item]));
			return found.flatMap((id) => (byId.has(id) ? [byId.get(id) as T] : []));
		};
		return {
			topics: pick(ids(this.topics, q, limit), this.source.topics, (t) => t.topic_id)
				.map((t) => ({ topic_id: t.topic_id, name: t.name }))
				// A topic whose name starts with the query comes first ("State complexity of
				// operations" before "Nondeterministic state complexity"); the sort is stable.
				.sort(
					(a, b) =>
						Number(!fold(a.name).startsWith(fold(q))) - Number(!fold(b.name).startsWith(fold(q)))
				),
			authors: pick(ids(this.authors, q, limit), this.source.authors, (a) => a.author_id),
			venues: pick(ids(this.venues, q, limit), this.source.venues, (v) => v.venue_id),
			works: pick(ids(this.works, q, limit), this.source.works, (w) => w.work_id)
		};
	}
}
