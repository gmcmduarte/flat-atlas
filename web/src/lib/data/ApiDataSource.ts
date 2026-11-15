import type { DataSource } from './DataSource';

const notImplemented = (): never => {
	throw new Error('ApiDataSource is not implemented yet (server stage, P3-04)');
};

/** Placeholder for the REST implementation that arrives with the server stage. */
export class ApiDataSource implements DataSource {
	getTopics = notImplemented;
	getTopic = notImplemented;
	getWork = notImplemented;
	getAuthor = notImplemented;
	getVenue = notImplemented;
	search = notImplemented;
	getMap = notImplemented;
}
