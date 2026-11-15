import { defineEnvVars } from '@sveltejs/kit/env';

// Public settings, read at build time (`PUBLIC_DATA_SOURCE=api npm run build`). Both are optional.
export const variables = defineEnvVars({
	PUBLIC_DATA_SOURCE: {
		public: true,
		static: true,
		description: '`static` (JSON files, default) or `api` (REST; server stage, not built yet).',
		schema: (value) => {
			if (value === undefined || value === '' || value === 'static') return 'static';
			if (value === 'api') return 'api';
			throw new Error(`PUBLIC_DATA_SOURCE must be "static" or "api", not "${value}"`);
		}
	},
	PUBLIC_DATA_DIR: {
		public: true,
		static: true,
		description: 'Folder under `static/` that the static data source reads.',
		schema: (value) => value || 'data-fixture'
	}
});
