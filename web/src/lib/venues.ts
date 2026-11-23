import type { DataVenue } from '#lib/data/types.js';

/**
 * A venue the site lists as one conference series: a venue that no other venue continues,
 * with the venues it continued (WIA before CIAA, DCAGRS before DCFS). `meta.json` lists every
 * venue record of the release; the banner and the About page count series, not records.
 */
export interface VenueSeries {
	current: DataVenue;
	/** Earlier venues of the series, oldest first. */
	predecessors: DataVenue[];
	/** First year of the oldest venue in the series. */
	firstYear: number;
}

export function venueSeries(venues: DataVenue[]): VenueSeries[] {
	const byId = new Map(venues.map((v) => [v.venue_id, v]));
	const continued = new Set(venues.flatMap((v) => v.successor_of));
	let heads = venues.filter((v) => !continued.has(v.venue_id));
	// A cycle in successor_of would leave no head: show every record as its own series.
	if (heads.length === 0) heads = venues;
	const series = heads.map((current) => {
		const predecessors: DataVenue[] = [];
		const seen = new Set([current.venue_id]);
		const walk = (v: DataVenue) => {
			for (const id of v.successor_of) {
				const p = byId.get(id);
				if (p && !seen.has(id)) {
					seen.add(id);
					predecessors.push(p);
					walk(p);
				}
			}
		};
		walk(current);
		predecessors.sort((a, b) => a.first_year - b.first_year || a.acronym.localeCompare(b.acronym));
		const firstYear = Math.min(current.first_year, ...predecessors.map((p) => p.first_year));
		return { current, predecessors, firstYear };
	});
	return series.sort(
		(a, b) => a.firstYear - b.firstYear || a.current.acronym.localeCompare(b.current.acronym)
	);
}

/** "a", "a and b", "a, b and c". */
export function joinList(items: string[]): string {
	if (items.length <= 1) return items.join('');
	return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}

const MONTHS = [
	'January',
	'February',
	'March',
	'April',
	'May',
	'June',
	'July',
	'August',
	'September',
	'October',
	'November',
	'December'
];

/** "2026-11-20" to "20 November 2026" (no locale data, so the server and the browser agree). */
export function formatDate(iso: string): string {
	const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
	if (!m) return iso;
	const month = MONTHS[Number(m[2]) - 1];
	return month ? `${Number(m[3])} ${month} ${m[1]}` : iso;
}

/**
 * The one sentence that says what the release covers, written from `meta.json`:
 * "2,333 papers from 3 conference series (DLT, CIAA and DCFS, with their predecessors WIA and DCAGRS)".
 */
export function coverageSentence(meta: { works: number; venues: DataVenue[] }): string {
	const series = venueSeries(meta.venues);
	const n = series.length;
	const names = joinList(series.map((s) => s.current.acronym));
	const earlier = series.flatMap((s) => s.predecessors.map((p) => p.acronym));
	const papers = `${meta.works.toLocaleString('en')} papers`;
	const tail =
		earlier.length > 0
			? `, with ${earlier.length === 1 ? 'its predecessor' : 'their predecessors'} ${joinList(earlier)}`
			: '';
	return `${papers} from ${n} conference series (${names}${tail})`;
}
