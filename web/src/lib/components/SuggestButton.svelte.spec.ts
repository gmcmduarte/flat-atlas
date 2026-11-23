import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import SuggestButton from './SuggestButton.svelte';

describe('SuggestButton', () => {
	it('offers the primary form of the entity type first, with the id filled in', () => {
		render(SuggestButton, {
			entity: { type: 'author', id: 'A123', name: 'Ada Example' },
			currentValue: 'Ada Example, 3 papers'
		});
		const links = screen.getAllByRole('link');
		const primary = links.find((l) => l.getAttribute('data-suggest') === 'primary')!;
		const url = new URL(primary.getAttribute('href')!);
		expect(url.searchParams.get('template')).toBe('author-merge-split.yml');
		expect(url.searchParams.get('entity_id')).toBe('A123');
		expect(links.length).toBe(2);
		expect(screen.getByRole('heading', { level: 2, name: 'Suggest a change' })).toBeTruthy();
	});
});
