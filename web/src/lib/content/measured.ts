/**
 * Numbers the Methods and Sources pages state that are measured by the pipeline, not read from
 * `meta.json`. They describe ONE release; update them (and `release`) whenever the tagger or the
 * release changes. Sources: DECISIONS D-100, D-102; reports/coverage-pilot.md; PROGRESS P1-08/P1-09.
 */
export const MEASURED = {
	release: 'v2026.11.0',
	tagger: 'tagger-3',
	/** Works in the labelled set, and how many of them were kept back to measure (D-61, D-100). */
	labelled: 682,
	heldOut: 159,
	/** Agreement with the reference labels on the held-out works, with 90 % intervals (D-100). */
	level0: {
		precision: 0.739,
		recall: 0.785,
		f1: 0.762,
		recallRange: [0.74, 0.828],
		precisionRange: [0.692, 0.785]
	},
	level1: {
		precision: 0.805,
		recall: 0.618,
		f1: 0.7,
		recallRange: [0.568, 0.668],
		precisionRange: [0.757, 0.852]
	},
	/** Share of works whose main topic changes under another training seed (D-101): one model, five. */
	seedChange: { single: 0.075, bagged: 0.04 },
	/** In the held-out check, tags stated at 80 to 90 % were right this often (48 tags, D-100 notes). */
	calibrationBin: { stated: '80 to 90 %', observed: 0.67, n: 48 },
	/** Links between topics in this release, strongest 10 per topic and type (D-102). */
	edges: { related: 102, buildsOn: 51, sharedCommunity: 973 },
	/** Links between the pilot's papers that both ends of are in the atlas (D-102). */
	citationLinks: 2211,
	/** Share of papers with an abstract from any source, and with a reference list (coverage report). */
	abstractShare: 26,
	referenceListShare: 88,
	/** Papers whose tags the atlas lists at most (topic pages, D-103). */
	topicPagePapers: 50
} as const;

export const pct = (x: number, digits = 0) => `${(x * 100).toFixed(digits)} %`;
