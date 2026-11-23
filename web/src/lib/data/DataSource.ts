import type {
	Author,
	DataInfo,
	MapLayout,
	SearchResults,
	Topic,
	TopicPage,
	Venue,
	Work
} from './types';

/**
 * What the pages need from the data. Two implementations: `StaticDataSource` (JSON files, the
 * pilot stage) and `ApiDataSource` (REST, the server stage). Moving between them is one setting
 * (PUBLIC_DATA_SOURCE); no page knows which one it has (PLAN §2.3).
 *
 * The `get*` methods resolve to `null` when the record does not exist.
 */
export interface DataSource {
	getTopics(): Promise<Topic[]>;
	getTopic(topicId: string): Promise<TopicPage | null>;
	getWork(workId: string): Promise<Work | null>;
	getAuthor(authorId: string): Promise<Author | null>;
	getVenue(venueId: string): Promise<Venue | null>;
	/** Up to `limit` results per group (topics, authors, venues, works). */
	search(query: string, limit?: number): Promise<SearchResults>;
	getMeta(): Promise<DataInfo | null>;
	getMap(): Promise<MapLayout>;
}
