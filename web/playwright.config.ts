import { defineConfig } from '@playwright/test';

// One smoke test against the production build of the fixture data (what CI deploys without the
// real export). Port 4173 is `vite preview`'s default.
export default defineConfig({
	testDir: 'e2e',
	webServer: {
		command: 'npm run build && npm run preview -- --port 4173 --strictPort',
		port: 4173,
		reuseExistingServer: !process.env.CI,
		timeout: 180_000
	},
	use: { baseURL: 'http://localhost:4173' },
	reporter: process.env.CI ? 'github' : 'list'
});
