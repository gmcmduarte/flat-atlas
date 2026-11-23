import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import PaperList from './PaperList.svelte';

const row = (
	work_id: string,
	title: string,
	year: number,
	cited_by_count: number,
	confidence?: number,
	low_confidence = false
) => ({
	work_id,
	title,
	year,
	venue_acronym: 'CONF',
	authors: ['Ada One', 'Bo Two'],
	n_authors: 4,
	cited_by_count,
	confidence,
	low_confidence
});

const papers = [
	row('A', 'Old and cited', 2000, 90, 0.9),
	row('B', 'New and uncited', 2022, 0, 0.9),
	row('C', 'Middle', 2010, 10, 0.95),
	row('W', 'A weak match', 2024, 500, 0.27, true)
];

const titles = () => screen.getAllByRole('link').map((a) => a.textContent);

describe('PaperList', () => {
	it('lists papers with authors, venue, year, citations and confidence', () => {
		render(PaperList, { papers, label: 'Papers' });
		const item = screen.getByRole('link', { name: 'Old and cited' }).closest('li') as HTMLElement;
		expect(within(item).getByText('Ada One, Bo Two et al.')).toBeTruthy();
		expect(item.textContent?.replace(/\s+/g, ' ')).toContain('CONF 2000 · 90 citations');
		expect(within(item).getByText('90%')).toBeTruthy();
	});

	it('sorts by relevance first, and the switch changes the order', async () => {
		render(PaperList, { papers });
		expect(titles()).toEqual(['Old and cited', 'Middle', 'New and uncited', 'A weak match']);
		await fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'newest' } });
		expect(titles()).toEqual(['New and uncited', 'Middle', 'Old and cited', 'A weak match']);
		await fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'oldest' } });
		expect(titles()).toEqual(['Old and cited', 'Middle', 'New and uncited', 'A weak match']);
		await fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'cited' } });
		expect(titles()).toEqual(['Old and cited', 'Middle', 'New and uncited', 'A weak match']);
	});

	it('puts weak matches in their own group after the others, whatever the order', async () => {
		render(PaperList, { papers });
		expect(screen.getByRole('heading', { name: 'Weak matches (1)' })).toBeTruthy();
		await fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'newest' } });
		expect(titles().at(-1)).toBe('A weak match');
		expect(screen.getByText(/weak match/, { selector: '.label' })).toBeTruthy();
	});

	it('has no relevance order for rows without a confidence, and starts where asked', () => {
		render(PaperList, {
			papers: papers.map((p) => ({ ...p, confidence: undefined, low_confidence: undefined })),
			initialSort: 'newest'
		});
		const options = screen.getAllByRole('option').map((o) => o.textContent);
		expect(options).toEqual(['Most cited', 'Newest', 'Oldest first']);
		expect(titles()[0]).toBe('A weak match');
	});

	it('says so when there are no papers', () => {
		render(PaperList, { papers: [], emptyText: 'None here.' });
		expect(screen.getByText('None here.')).toBeTruthy();
		expect(screen.queryByLabelText('Sort by')).toBeNull();
	});
});
