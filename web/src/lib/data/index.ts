import { resolve } from '$app/paths';
import { PUBLIC_DATA_DIR, PUBLIC_DATA_SOURCE } from '$app/env/public';
import { ApiDataSource } from './ApiDataSource';
import type { DataSource } from './DataSource';
import { StaticDataSource } from './StaticDataSource';

export type { DataSource } from './DataSource';
export * from './types';

/**
 * The data source the site uses, chosen by PUBLIC_DATA_SOURCE (see `src/env.ts`). The static
 * source reads the folder PUBLIC_DATA_DIR under `static/`: the hand-written fixture until the
 * pipeline's export is wired in.
 *
 * Call it from a load function and pass that function's `fetch`: `resolve` gives a base-aware
 * URL (relative during server rendering), and SvelteKit's `fetch` understands it in both places.
 */
export function getDataSource(fetchFn: typeof fetch): DataSource {
	if (PUBLIC_DATA_SOURCE === 'api') return new ApiDataSource();
	// `resolve('/')` is the base path with a trailing slash (relative while rendering on the server).
	const root = resolve('/');
	return new StaticDataSource(
		fetchFn,
		`${root.endsWith('/') ? root : `${root}/`}${PUBLIC_DATA_DIR}`
	);
}
