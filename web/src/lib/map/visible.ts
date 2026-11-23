import { ancestorsOf, isBelow, type MapIndex } from './model';

/**
 * Which topics the map draws is a *cut* of the topic tree: starting from the level-0 topics, an
 * expanded topic is replaced by its children (and drawn as a faint hull behind them); anything
 * else is a bubble. This file is pure logic: no Sigma, no DOM.
 */

/** About this many nodes (bubbles plus hulls) are drawn at most (PLAN §11.4). */
export const NODE_CAP = 150;
/** A collapsed bubble expands by itself when its on-screen radius exceeds this many pixels. */
export const ZOOM_EXPAND_PX = 120;
/** An expanded topic collapses by itself when its on-screen radius falls below this. */
export const ZOOM_COLLAPSE_PX = 60;

export interface MapState {
	/** Expanded topics, least recently touched first. */
	expanded: string[];
	/** The topic the user is looking at (shown in the panel), or null. */
	selected: string | null;
}

export const EMPTY_STATE: MapState = { expanded: [], selected: null };

export interface Cut {
	/** Bubbles, depth first (the order of the list view). */
	bubbles: string[];
	/** Expanded topics with at least one child, drawn as hulls, in the same order. */
	hulls: string[];
}

export function cutOf(index: MapIndex, expanded: Iterable<string>): Cut {
	const open = new Set(expanded);
	const bubbles: string[] = [];
	const hulls: string[] = [];
	const visit = (id: string) => {
		const topic = index.topics.get(id);
		if (!topic) return;
		if (open.has(id) && topic.children.length > 0) {
			hulls.push(id);
			for (const child of topic.children) visit(child);
		} else {
			bubbles.push(id);
		}
	};
	for (const root of index.roots) visit(root);
	return { bubbles, hulls };
}

export function drawnCount(cut: Cut): number {
	return cut.bubbles.length + cut.hulls.length;
}

/** The nearest topic at or above `id` that is in `targets`, following primary parents. */
export function nearestIn(index: MapIndex, id: string, targets: Set<string>): string | null {
	if (targets.has(id)) return id;
	for (const ancestor of ancestorsOf(index, id)) if (targets.has(ancestor)) return ancestor;
	return null;
}

function touch(list: string[], id: string): string[] {
	return [...list.filter((x) => x !== id), id];
}

/** Drops `id` and every expanded topic below it. */
function dropSubtree(index: MapIndex, expanded: string[], id: string): string[] {
	return expanded.filter((x) => x !== id && !isBelow(index, x, id));
}

export interface ExpandOptions {
	cap?: number;
	/** Topics that must stay as they are (on screen right now): never collapsed to make room. */
	protect?: Iterable<string>;
}

export interface ExpandResult {
	state: MapState;
	/** True when the expansion would break the cap and nothing could be collapsed to make room. */
	refused: boolean;
}

/**
 * Expands `id` (and, so that it is visible, all its ancestors) and selects it. When the cut would
 * exceed the cap, the least recently touched expanded topics that are neither `id`, nor an
 * ancestor of it, nor protected, are collapsed first.
 */
export function expandTopic(
	index: MapIndex,
	state: MapState,
	id: string,
	{ cap = NODE_CAP, protect = [] }: ExpandOptions = {}
): ExpandResult {
	const topic = index.topics.get(id);
	if (!topic) return { state, refused: false };
	const path = ancestorsOf(index, id).reverse();
	const keep = new Set([...path, id]);
	for (const p of protect) {
		keep.add(p);
		for (const a of ancestorsOf(index, p)) keep.add(a);
	}
	let expanded = state.expanded;
	for (const p of path) expanded = touch(expanded, p);
	if (topic.children.length > 0) expanded = touch(expanded, id);
	while (drawnCount(cutOf(index, expanded)) > cap) {
		const victim = expanded.find((x) => !keep.has(x));
		if (victim === undefined) return { state, refused: true };
		expanded = dropSubtree(index, expanded, victim);
	}
	return { state: { expanded, selected: id }, refused: false };
}

/** Collapses `id` and everything open below it; the selection moves to `id`. */
export function collapseTopic(index: MapIndex, state: MapState, id: string): MapState {
	return { expanded: dropSubtree(index, state.expanded, id), selected: id };
}

/**
 * The Back control: collapses the deepest expanded topic (the most recently touched among the
 * deepest) and selects it; with nothing expanded it only clears the selection.
 */
export function goBack(
	index: MapIndex,
	state: MapState
): { state: MapState; collapsed: string | null } {
	let target: string | null = null;
	let depth = -1;
	for (const id of state.expanded) {
		const level = index.topics.get(id)?.level ?? 0;
		if (level >= depth) {
			depth = level;
			target = id;
		}
	}
	if (target === null) return { state: { ...state, selected: null }, collapsed: null };
	return { state: collapseTopic(index, state, target), collapsed: target };
}

/** The topic that stands for the whole view in the URL: the selection, else the deepest open one. */
export function focusOf(index: MapIndex, state: MapState): string | null {
	if (state.selected && index.topics.has(state.selected)) return state.selected;
	let target: string | null = null;
	let depth = -1;
	for (const id of state.expanded) {
		const level = index.topics.get(id)?.level ?? 0;
		if (level >= depth) {
			depth = level;
			target = id;
		}
	}
	return target;
}

/** The state that shows `focus`: its ancestors and itself (when it has children) open. */
export function stateForFocus(index: MapIndex, focus: string | null): MapState {
	if (!focus || !index.topics.has(focus)) return EMPTY_STATE;
	return expandTopic(index, EMPTY_STATE, focus).state;
}

export interface OnScreen {
	id: string;
	/** Radius on screen in pixels. */
	radiusPx: number;
	/** Whether the disc meets the viewport. */
	visible: boolean;
	/** Centre in pixels from the top left of the map. */
	cx?: number;
	cy?: number;
}

export interface Viewport {
	width: number;
	height: number;
	/**
	 * False while the camera shows everything (or more): the first view never opens a bubble by
	 * itself, however big the bubbles are on a small layout. Unset counts as true.
	 */
	zoomedIn?: boolean;
}

export interface ZoomChanges {
	expand: string[];
	collapse: string[];
}

/**
 * Semantic zoom with hysteresis: given the on-screen radius of every bubble and hull, which
 * topics open or close by themselves. A bubble opens above `ZOOM_EXPAND_PX`; an expanded topic
 * closes below `ZOOM_COLLAPSE_PX`. Only topics that meet the viewport are considered. A hull
 * contains its descendants, so when it is small they are smaller still: closing the outermost
 * small hull is enough.
 */
export function zoomChanges(
	index: MapIndex,
	cut: Cut,
	screen: OnScreen[],
	{
		expandAt = ZOOM_EXPAND_PX,
		collapseAt = ZOOM_COLLAPSE_PX,
		viewport
	}: { expandAt?: number; collapseAt?: number; viewport?: Viewport } = {}
): ZoomChanges {
	const hullSet = new Set(cut.hulls);
	const radius = (id: string) => screen.find((s) => s.id === id)?.radiusPx ?? 0;
	const expand: string[] = [];
	const collapse: string[] = [];
	for (const s of screen) {
		if (!s.visible) continue;
		const topic = index.topics.get(s.id);
		if (!topic) continue;
		if (hullSet.has(s.id)) {
			if (s.radiusPx < collapseAt) collapse.push(s.id);
		} else if (topic.children.length > 0 && s.radiusPx > expandAt && viewport?.zoomedIn !== false) {
			// Zooming in opens what is in focus: a big neighbour at the edge of the screen stays shut.
			const central =
				!viewport ||
				s.cx === undefined ||
				s.cy === undefined ||
				(Math.abs(s.cx - viewport.width / 2) < viewport.width * 0.3 &&
					Math.abs(s.cy - viewport.height / 2) < viewport.height * 0.3);
			if (central) expand.push(s.id);
		}
	}
	// One at a time, the biggest on screen first; the next pass opens the next.
	expand.sort((a, b) => radius(b) - radius(a));
	expand.length = Math.min(expand.length, 1);
	// Collapsing a hull takes its descendants with it: report the outermost ones only.
	const outermost = collapse.filter(
		(id) => !collapse.some((o) => o !== id && isBelow(index, id, o))
	);
	return { expand, collapse: outermost };
}
