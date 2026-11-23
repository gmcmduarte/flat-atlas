import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import ConfidenceBadge from './ConfidenceBadge.svelte';
import type { Provenance } from '#lib/data/index.js';

const provenance = (
	flags: string[] = [],
	signals: Record<string, number> = { lex_title: 1, emb_desc: 0.9 }
): Provenance => ({
	method: 'fusion',
	signals,
	tagger_version: 'tagger-3',
	taxonomy_version: '1',
	flags
});

describe('ConfidenceBadge', () => {
	it('shows the confidence as a percentage', () => {
		render(ConfidenceBadge, { value: 0.874, title: 'Edge confidence' });
		const badge = screen.getByText('87%');
		expect(badge.getAttribute('title')).toBe('Edge confidence');
	});

	it('adds the band and a plain-language provenance sentence for a tag', () => {
		render(ConfidenceBadge, { value: 0.93, provenance: provenance() });
		const badge = screen.getByText(/93%/);
		expect(badge.textContent).toContain('high');
		const tip = badge.getAttribute('title') ?? '';
		expect(tip).toContain('topic words in the title (100%)');
		expect(tip).toContain('Method: learned combination of signals (fusion, tagger-3)');
	});

	it('prints the explanation when asked, so it does not need a mouse', () => {
		render(ConfidenceBadge, { value: 0.93, provenance: provenance(), showExplanation: true });
		expect(screen.getByText(/Based on topic words in the title/)).toBeTruthy();
	});

	it('labels a low-confidence tag a weak match', () => {
		render(ConfidenceBadge, {
			value: 0.27,
			provenance: provenance(['low_confidence'], { emb_desc: 0.3 })
		});
		const badge = screen.getByText(/27%/);
		expect(badge.textContent).toContain('weak match');
		expect(badge.getAttribute('title')).toContain('Weak match');
	});

	it('marks a weak match from a paper list row without a provenance', () => {
		render(ConfidenceBadge, { value: 0.3, weak: true, title: 'best guess' });
		expect(screen.getByText(/30%/).textContent).toContain('weak match');
	});
});
