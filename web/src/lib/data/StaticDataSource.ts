import type { DataSource } from './DataSource';
import type {
	Author,
	DataInfo,
	MapLayout,
	SearchIndex,
	SearchResults,
	Topic,
	TopicPage,
	Venue,
	Work
} from './types';
import type { SearchEngine } from '../search/engine';

/**
 * Shard name of an ID: the first two hex characters of its SHA-256 (256 shards, PLAN §11.2).
 * The pipeline must use the same rule when it writes `works/<shard>.json` and `authors/<shard>.json`.
 */
export async function shardOf(id: string): Promise<string> {
	const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(id));
	return [...new Uint8Array(digest).slice(0, 1)]
		.map((b) => b.toString(16).padStart(2, '0'))
		.join('');
}

/** Reads the JSON files the pipeline exports (see PLAN §11.2) from `baseUrl`. */
export class StaticDataSource implements DataSource {
	private readonly cache = new Map<string, Promise<unknown>>();

	/**
	 * @param fetchFn SvelteKit's `fetch` from a load function (works during prerendering) or `fetch`.
	 * @param baseUrl where the data folder is served, for example `/flat-atlas/data-fixture`.
	 */
	constructor(
		private readonly fetchFn: typeof fetch,
		private readonly baseUrl: string
	) {}

	/** Fetches one JSON file once; `null` for a missing file (404). */
	private json<T>(path: string): Promise<T | null> {
		let pending = this.cache.get(path) as Promise<T | null> | undefined;
		if (!pending) {
			pending = this.load<T>(path);
			this.cache.set(path, pending);
			// A failed load is not kept, so the next call tries again.
			pending.catch(() => this.cache.delete(path));
		}
		return pending;
	}

	private async load<T>(path: string): Promise<T | null> {
		const url = `${this.baseUrl}/${path}`;
		const res = await this.fetchFn(url);
		if (res.status === 404) return null;
		if (!res.ok) throw new Error(`Could not load ${url}: HTTP ${res.status}`);
		try {
			return (await res.json()) as T;
		} catch {
			// A host that answers a missing file with an HTML page and status 200.
			throw new Error(`Could not load ${url}: the response is not JSON`);
		}
	}

	private async fromShard<T>(dir: string, id: string): Promise<T | null> {
		const shard = await this.json<Record<string, T>>(`${dir}/${await shardOf(id)}.json`);
		return shard?.[id] ?? null;
	}

	async getTopics(): Promise<Topic[]> {
		return (await this.json<Topic[]>('topics.json')) ?? [];
	}

	getTopic(topicId: string): Promise<TopicPage | null> {
		return this.json<TopicPage>(`topic/${encodeURIComponent(topicId)}.json`);
	}

	getWork(workId: string): Promise<Work | null> {
		return this.fromShard<Work>('works', workId);
	}

	getAuthor(authorId: string): Promise<Author | null> {
		return this.fromShard<Author>('authors', authorId);
	}

	getVenue(venueId: string): Promise<Venue | null> {
		return this.json<Venue>(`venue/${encodeURIComponent(venueId)}.json`);
	}

	private engine: Promise<SearchEngine> | undefined;

	/** The search index is fetched and built on the first search only (it is the biggest file). */
	private searchEngine(): Promise<SearchEngine> {
		this.engine ??= (async () => {
			const [{ SearchEngine }, index] = await Promise.all([
				import('../search/engine'),
				this.json<SearchIndex>('search/index.json')
			]);
			return new SearchEngine(index ?? { topics: [], authors: [], venues: [], works: [] });
		})();
		// A failed load is not kept, so the next search tries again.
		this.engine.catch(() => (this.engine = undefined));
		return this.engine;
	}

	async search(query: string, limit = 10): Promise<SearchResults> {
		return (await this.searchEngine()).search(query, limit);
	}

	getMeta(): Promise<DataInfo | null> {
		return this.json<DataInfo>('meta.json');
	}

	async getMap(): Promise<MapLayout> {
		return (await this.json<MapLayout>('map.json')) ?? { nodes: [] };
	}
}
