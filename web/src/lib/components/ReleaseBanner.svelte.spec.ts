import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import ReleaseBanner from './ReleaseBanner.svelte';
import type { DataInfo } from '#lib/data/types.js';

const venue = (id: string, acronym: string, first_year: number, successor_of: string[] = []) => ({
	venue_id: id,
	acronym,
	name: acronym,
	first_year,
	last_year: null,
	successor_of
});

const meta: DataInfo = {
	release: 'v2026.11.0',
	date: '2026-11-20',
	tagger_version: 'tagger-3',
	taxonomy_version: '1',
	aggregate_version: 'agg-1',
	works: 2333,
	works_by_tag_status: { tagged: 2126, low_confidence: 137, untagged: 70 },
	topics: 181,
	venues: [venue('V1', 'DLT', 1993), venue('V2', 'CIAA', 2000, ['V3']), venue('V3', 'WIA', 1996)],
	source_fetch_dates: {}
};

describe('ReleaseBanner', () => {
	it('names the release, its date and the venues from the data', () => {
		render(ReleaseBanner, { meta });
		const banner = screen.getByRole('complementary', { name: 'About this data' });
		expect(banner.textContent).toContain('2,333 papers from 2 conference series (DLT and CIAA');
		expect(banner.textContent).toContain('predecessor WIA');
		expect(banner.textContent).toContain('release v2026.11.0, 20 November 2026');
		expect(screen.getByRole('link', { name: 'How they are made' })).toBeTruthy();
	});

	it('says plainly when the data is the fixture', () => {
		render(ReleaseBanner, { meta: { ...meta, fixture: true } });
		expect(screen.getByText(/Fixture data/)).toBeTruthy();
		expect(screen.queryByText(/release v2026/)).toBeNull();
	});
});
