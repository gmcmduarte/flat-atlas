import type { LateralEdgeType } from '#lib/data/index.js';

/** Colours and wording of the map. No Sigma here. */

export type Scheme = 'light' | 'dark';

/**
 * Sigma blends with `ONE, ONE_MINUS_SRC_ALPHA` but does not premultiply the colours it is given,
 * so a translucent colour must be premultiplied here or it comes out brighter than intended.
 */
function premultiplied(r: number, g: number, b: number, alpha: number): string {
	const a = Math.min(1, Math.max(0, alpha));
	return `rgba(${Math.round(r * a)}, ${Math.round(g * a)}, ${Math.round(b * a)}, ${a.toFixed(3)})`;
}

/** Twelve distinguishable hues (Tableau-like), cycled over the level-0 topics, by index. */
const HUES: [number, number, number][] = [
	[31, 119, 180],
	[255, 127, 14],
	[44, 160, 44],
	[214, 39, 40],
	[148, 103, 189],
	[140, 86, 75],
	[227, 119, 194],
	[23, 190, 207],
	[188, 189, 34],
	[82, 82, 164],
	[0, 128, 128],
	[199, 133, 0]
];

/** `rgba()` colour of a bubble: the colour of its level-0 topic, paler for deeper levels. */
export function bubbleColour(rootIndex: number, level: number, scheme: Scheme, alpha = 1): string {
	const [r, g, b] = HUES[((rootIndex % HUES.length) + HUES.length) % HUES.length];
	// Deeper levels mix towards white (light scheme) or stay a little brighter (dark scheme).
	const mix = Math.min(0.55, level * 0.22);
	const k = scheme === 'light' ? mix : mix * 0.5;
	const c = (v: number) => Math.round(v + (255 - v) * k);
	return premultiplied(c(r), c(g), c(b), alpha);
}

/** The faint disc behind the children of an expanded topic. */
export function hullColour(rootIndex: number, scheme: Scheme, fade = 1): string {
	return bubbleColour(rootIndex, 0, scheme, (scheme === 'light' ? 0.1 : 0.16) * fade);
}

export interface EdgeStyle {
	/** Short name in the toolbar. */
	label: string;
	/** What an edge of this type says. */
	meaning: string;
	/** What its width stands for. */
	weight: string;
	/** What its opacity (the stored confidence) stands for. */
	confidence: string;
	/** Sigma edge program. */
	program: 'line' | 'arrow';
	/** rgb triple per colour scheme. */
	colour: Record<Scheme, [number, number, number]>;
	/** Thickness range in pixels for the weakest and the strongest edge on screen. */
	width: [number, number];
	/** Text for the legend swatch's description. */
	drawn: string;
}

export const EDGE_STYLES: Record<LateralEdgeType, EdgeStyle> = {
	related: {
		label: 'Related',
		meaning: 'Topics whose papers overlap more often than chance.',
		weight: 'Width: how strongly the two topics co-occur on the same papers (normalised PMI).',
		confidence: 'Opacity: how stable the link is when the papers are resampled (200 resamples).',
		program: 'line',
		colour: { light: [15, 118, 110], dark: [94, 234, 212] },
		width: [1.5, 6],
		drawn: 'Solid teal line, no arrow'
	},
	'builds-on': {
		label: 'Builds on',
		meaning: 'Papers in the first topic cite papers in the second more often than chance.',
		weight: 'Width: the excess share of the first topic’s citations that go to the second.',
		confidence: 'Opacity: one minus the permutation p-value (how unlikely it is by chance).',
		program: 'arrow',
		colour: { light: [194, 65, 12], dark: [253, 186, 116] },
		width: [2, 6],
		drawn: 'Orange arrow, pointing at the topic that is built on'
	},
	'shared-community': {
		label: 'Shared community',
		meaning: 'Topics written by many of the same authors.',
		weight: 'Width: cosine similarity of the two topics’ author activity.',
		confidence: 'Opacity: how stable the link is when the authors are resampled (200 resamples).',
		program: 'line',
		colour: { light: [109, 40, 217], dark: [196, 181, 253] },
		width: [1, 4],
		drawn: 'Thin violet line, no arrow'
	}
};

/** Edge colour and thickness for a normalised weight (0..1) and a confidence (0..1). */
export function edgeAppearance(
	type: LateralEdgeType,
	scheme: Scheme,
	weight: number,
	confidence: number
): { colour: string; size: number } {
	const s = EDGE_STYLES[type];
	const [r, g, b] = s.colour[scheme];
	const alpha = 0.3 + 0.55 * Math.min(1, Math.max(0, confidence));
	const size = s.width[0] + (s.width[1] - s.width[0]) * Math.min(1, Math.max(0, weight));
	return { colour: premultiplied(r, g, b, alpha), size };
}

/** A thin neutral line to the other parent of a topic with several parents. */
export function ghostColour(scheme: Scheme): string {
	return scheme === 'light'
		? premultiplied(90, 100, 120, 0.55)
		: premultiplied(180, 190, 210, 0.55);
}
