import type { LateralEdgeType, TopicPage } from '#lib/data/index.js';
import { ancestorsOf, type MapIndex } from './model';
import type { Cut } from './visible';

/** The strongest edges kept per bubble and edge type. */
export const TOP_K = 3;

export const EDGE_TYPES: LateralEdgeType[] = ['related', 'builds-on', 'shared-community'];

/** An edge between two bubbles, ready to draw. `from` builds on `to` for `builds-on`. */
export interface MapEdge {
	key: string;
	type: LateralEdgeType;
	from: string;
	to: string;
	/** Only `builds-on` has a direction. */
	directed: boolean;
	weight: number;
	/** Not comparable across edge types. */
	confidence: number;
	/**
	 * Stored links behind this edge when it is rolled up from topics inside a collapsed bubble;
	 * 0 when the stored edge joins the two bubbles themselves.
	 */
	rolledUp: number;
}

/**
 * Edges of one type between the bubbles of the cut.
 *
 * The pipeline stores an edge between any two topics that are not in each other's subtree, each
 * computed on the topics' subtree memberships (D-102), so an edge between two bubbles is a stored
 * edge and nothing is summed. A pair without one is joined by the strongest stored edge between
 * topics inside the two bubbles (max, because NPMI, excess share and cosine do not add). Only the
 * pages of the bubbles themselves are needed: each lists the edges of its own topic, whatever
 * the other end is.
 *
 * Per bubble the `k` strongest edges are kept; an edge stays when either end keeps it.
 */
export function aggregateEdges(
	index: MapIndex,
	cut: Cut,
	pages: ReadonlyMap<string, TopicPage>,
	type: LateralEdgeType,
	k: number = TOP_K
): MapEdge[] {
	const bubbles = new Set(cut.bubbles);
	const cutOf = new Map<string, string | null>();
	const bubbleOf = (id: string): string | null => {
		const known = cutOf.get(id);
		if (known !== undefined) return known;
		let found: string | null = null;
		if (bubbles.has(id)) found = id;
		else for (const a of ancestorsOf(index, id)) if (bubbles.has(a)) found = a;
		cutOf.set(id, found);
		return found;
	};

	const best = new Map<string, MapEdge>();
	// Distinct stored links (by their two topics) behind each rolled-up pair.
	const links = new Map<string, Set<string>>();
	for (const bubble of cut.bubbles) {
		const page = pages.get(bubble);
		if (!page) continue;
		for (const e of page.edges[type]) {
			const other = bubbleOf(e.topic_id);
			if (other === null || other === bubble) continue;
			const direct = other === e.topic_id;
			// `out`: this topic builds on the other one.
			const from = e.direction === 'in' ? other : bubble;
			const to = e.direction === 'in' ? bubble : other;
			const directed = type === 'builds-on' && e.direction !== 'both';
			const [a, b] = directed || from < to ? [from, to] : [to, from];
			const key = `${type}|${a}|${b}`;
			const candidate: MapEdge = {
				key,
				type,
				from: a,
				to: b,
				directed,
				weight: e.weight,
				confidence: e.confidence,
				rolledUp: direct ? 0 : 1
			};
			if (!direct) {
				const pair = bubble < e.topic_id ? `${bubble}|${e.topic_id}` : `${e.topic_id}|${bubble}`;
				links.set(key, (links.get(key) ?? new Set()).add(pair));
			}
			const seen = best.get(key);
			// A stored edge between the bubbles beats a rolled-up one; then the stronger wins.
			if (
				!seen ||
				(candidate.rolledUp === seen.rolledUp
					? candidate.weight > seen.weight
					: candidate.rolledUp < seen.rolledUp)
			) {
				best.set(key, candidate);
			}
		}
	}
	for (const [key, edge] of best) {
		if (edge.rolledUp > 0) edge.rolledUp = links.get(key)?.size ?? 1;
	}
	return topPerNode([...best.values()], k);
}

/** Keeps an edge when it is among the `k` strongest of its source or of its target. */
export function topPerNode(edges: MapEdge[], k: number): MapEdge[] {
	const sorted = [...edges].sort((x, y) => y.weight - x.weight || (x.key < y.key ? -1 : 1));
	const count = new Map<string, number>();
	const kept: MapEdge[] = [];
	const take = (id: string): boolean => {
		const n = count.get(id) ?? 0;
		if (n >= k) return false;
		count.set(id, n + 1);
		return true;
	};
	for (const edge of sorted) {
		const a = take(edge.from);
		const b = take(edge.to);
		if (a || b) kept.push(edge);
	}
	return kept;
}

/** A thin grey link from a bubble to where its other parent is drawn. */
export interface GhostLink {
	key: string;
	from: string;
	/** A bubble or a hull. */
	to: string;
}

/**
 * Links from every bubble with more than one parent to the other parents, drawn at the nearest
 * bubble or hull above each. A link is left out when that target already contains the bubble
 * (the other parent lies inside the primary one's own chain).
 */
export function ghostLinks(index: MapIndex, cut: Cut): GhostLink[] {
	const drawn = new Set([...cut.bubbles, ...cut.hulls]);
	const out: GhostLink[] = [];
	for (const id of cut.bubbles) {
		const topic = index.topics.get(id);
		if (!topic) continue;
		const own = new Set([id, ...ancestorsOf(index, id)]);
		for (const ghost of topic.ghostParents) {
			let target: string | null = null;
			for (const candidate of [ghost, ...ancestorsOf(index, ghost)]) {
				if (drawn.has(candidate)) {
					target = candidate;
					break;
				}
			}
			if (target === null || own.has(target)) continue;
			out.push({ key: `ghost|${id}|${target}`, from: id, to: target });
		}
	}
	return out;
}

/** Edge weights scaled to 0..1 by the strongest one of the type shown. */
export function normaliseWeights(edges: MapEdge[]): Map<string, number> {
	const max = Math.max(0, ...edges.map((e) => e.weight));
	return new Map(edges.map((e) => [e.key, max > 0 ? Math.max(0, e.weight) / max : 0]));
}
