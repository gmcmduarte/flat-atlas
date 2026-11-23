export type SortKey = 'relevance' | 'cited' | 'newest' | 'oldest';

export const SORT_LABELS: Record<SortKey, string> = {
	relevance: 'Relevance',
	cited: 'Most cited',
	newest: 'Newest',
	oldest: 'Oldest first'
};

/** The fields the sorting needs: any paper row of the export has them. */
export interface Sortable {
	work_id: string;
	year: number;
	confidence: number;
	cited_by_count: number;
	low_confidence: boolean;
}

/** PLAN §11.3: relevance = tag confidence × log citations (+1 so an uncited paper still counts). */
export function relevance(p: Sortable): number {
	return p.confidence * Math.log(2 + p.cited_by_count);
}

const COMPARE: Record<SortKey, (a: Sortable, b: Sortable) => number> = {
	relevance: (a, b) => relevance(b) - relevance(a),
	cited: (a, b) => b.cited_by_count - a.cited_by_count || b.confidence - a.confidence,
	newest: (a, b) => b.year - a.year || b.cited_by_count - a.cited_by_count,
	oldest: (a, b) => a.year - b.year || b.cited_by_count - a.cited_by_count
};

/**
 * Sorts a copy of `papers`. Weakly matched papers always come after the normal ones (D-102);
 * inside each group the chosen order applies, ties broken by the work ID so the order is stable.
 */
export function sortPapers<T extends Sortable>(papers: readonly T[], key: SortKey): T[] {
	return [...papers].sort(
		(a, b) =>
			Number(a.low_confidence) - Number(b.low_confidence) ||
			COMPARE[key](a, b) ||
			a.work_id.localeCompare(b.work_id)
	);
}
