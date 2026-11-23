import type { Provenance } from './data/types';

/** How a signal reads in a sentence ("topic words in the title"). Unknown signals are skipped. */
const PHRASES: Record<string, string> = {
	lex_title: 'topic words in the title',
	lex_abstract: 'topic words in the abstract',
	lex_refs: 'topic words in the titles of the works it cites',
	emb_seed: "similarity to the topic's example papers",
	emb_desc: 'similarity to the topic description',
	venue_prior: 'a venue that often publishes on this topic',
	src_openalex: 'the topic that OpenAlex assigns'
};

/** A signal counts as evidence from this score up (scores are between 0 and 1). */
const STRONG = 0.5;
const MOST = 3;

export type Band = 'high' | 'medium' | 'low';

/** The word shown next to a confidence: calibrated, so 0.8 or more is rarely wrong. */
export function band(confidence: number): Band {
	if (confidence >= 0.8) return 'high';
	if (confidence >= 0.5) return 'medium';
	return 'low';
}

export function isWeakMatch(provenance: Provenance | undefined): boolean {
	return provenance?.flags.includes('low_confidence') ?? false;
}

/**
 * The tooltip and the visible line under a tag: what the tagger saw, in plain words, built from
 * the provenance struct (scores only; the texts themselves are never exported).
 */
export function explainProvenance(provenance: Provenance, confidence: number): string {
	const percent = Math.round(confidence * 100);
	const evidence = Object.entries(provenance.signals)
		.filter(([name, score]) => name in PHRASES && score >= STRONG)
		.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
		.slice(0, MOST)
		.map(([name, score]) => `${PHRASES[name]} (${Math.round(score * 100)}%)`);
	const parts: string[] = [];
	if (isWeakMatch(provenance)) {
		parts.push(
			`Weak match: no topic reached the confidence the tagger needs, so this is its best guess at ${percent}%.`
		);
	} else {
		parts.push(`Confidence ${percent}%.`);
	}
	parts.push(
		evidence.length > 0
			? `Based on ${evidence.join('; ')}.`
			: 'No single signal is strong; the confidence comes from several weak ones together.'
	);
	const how = provenance.method === 'fusion' ? 'learned combination of signals' : provenance.method;
	parts.push(`Method: ${how} (${provenance.method}, ${provenance.tagger_version}).`);
	return parts.join(' ');
}
