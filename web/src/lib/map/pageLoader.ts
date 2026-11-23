import type { DataSource, TopicPage } from '#lib/data/index.js';

/**
 * Loads topic pages for the map, a few at a time, each once. The map needs the pages of the
 * bubbles it draws (for their edges and key authors); the data source caches the files too, so
 * a page opened later is already there.
 */
export class PageLoader {
	private readonly pages = new Map<string, TopicPage>();
	private readonly pending = new Map<string, Promise<void>>();
	private active = 0;
	private readonly waiting: (() => void)[] = [];

	constructor(
		private readonly source: Pick<DataSource, 'getTopic'>,
		private readonly concurrency = 6
	) {}

	/** What has been loaded so far. */
	get loaded(): ReadonlyMap<string, TopicPage> {
		return this.pages;
	}

	/** Resolves when every page in `ids` has been tried; a failed page is simply missing. */
	async load(ids: Iterable<string>): Promise<void> {
		await Promise.all([...new Set(ids)].map((id) => this.one(id)));
	}

	private one(id: string): Promise<void> {
		if (this.pages.has(id)) return Promise.resolve();
		let promise = this.pending.get(id);
		if (!promise) {
			promise = this.slot().then(async () => {
				try {
					const page = await this.source.getTopic(id);
					if (page) this.pages.set(id, page);
				} catch {
					// the map works without the edges and authors of this topic
				} finally {
					this.pending.delete(id);
					this.release();
				}
			});
			this.pending.set(id, promise);
		}
		return promise;
	}

	private slot(): Promise<void> {
		if (this.active < this.concurrency) {
			this.active++;
			return Promise.resolve();
		}
		return new Promise((resolve) => this.waiting.push(resolve));
	}

	private release() {
		const next = this.waiting.shift();
		if (next) next();
		else this.active--;
	}
}
