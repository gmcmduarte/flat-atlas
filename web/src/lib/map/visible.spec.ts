import { describe, expect, it } from 'vitest';
import { sampleIndex } from './testIndex';
import {
	EMPTY_STATE,
	collapseTopic,
	cutOf,
	drawnCount,
	expandTopic,
	focusOf,
	goBack,
	stateForFocus,
	zoomChanges
} from './visible';

const index = sampleIndex();

describe('cutOf', () => {
	it('starts with the roots, biggest first', () => {
		const cut = cutOf(index, []);
		expect(cut.bubbles).toEqual(['a', 'b']);
		expect(cut.hulls).toEqual([]);
	});
	it('replaces an expanded topic by its children and keeps it as a hull', () => {
		const cut = cutOf(index, ['a']);
		expect(cut.bubbles).toEqual(['a1', 'a2', 'b']);
		expect(cut.hulls).toEqual(['a']);
		expect(drawnCount(cut)).toBe(4);
	});
	it('ignores an expanded leaf and an expanded child of a collapsed parent', () => {
		expect(cutOf(index, ['b1']).bubbles).toEqual(['a', 'b']);
		expect(cutOf(index, ['a1']).bubbles).toEqual(['a', 'b']);
	});
});

describe('expandTopic', () => {
	it('opens the ancestors too and selects the topic', () => {
		const { state } = expandTopic(index, EMPTY_STATE, 'a1');
		expect(state.expanded).toEqual(['a', 'a1']);
		expect(state.selected).toBe('a1');
		expect(cutOf(index, state.expanded).bubbles).toEqual(['a1x', 'a2', 'b']);
	});
	it('selects a leaf without expanding it', () => {
		const { state } = expandTopic(index, EMPTY_STATE, 'b1');
		expect(state.expanded).toEqual(['b']);
		expect(state.selected).toBe('b1');
	});
	it('collapses the least recently touched topic to respect the cap', () => {
		let state = expandTopic(index, EMPTY_STATE, 'b').state; // 3 drawn: a, b1, hull b
		state = expandTopic(index, state, 'a', { cap: 4 }).state; // a1, a2, b1 + hulls a, b = 5 > 4
		expect(state.expanded).toEqual(['a']);
	});
	it('does not collapse protected topics and refuses when nothing can give way', () => {
		const base = expandTopic(index, EMPTY_STATE, 'b').state;
		const result = expandTopic(index, base, 'a', { cap: 4, protect: ['b'] });
		expect(result.refused).toBe(true);
		expect(result.state).toBe(base);
	});
});

describe('collapse and back', () => {
	it('collapses a topic with everything open below it', () => {
		const open = expandTopic(index, EMPTY_STATE, 'a1').state;
		const state = collapseTopic(index, open, 'a');
		expect(state.expanded).toEqual([]);
		expect(state.selected).toBe('a');
	});
	it('goes back one level at a time, deepest first', () => {
		const open = expandTopic(index, EMPTY_STATE, 'a1').state;
		const first = goBack(index, open);
		expect(first.collapsed).toBe('a1');
		expect(first.state.expanded).toEqual(['a']);
		const second = goBack(index, first.state);
		expect(second.collapsed).toBe('a');
		const third = goBack(index, second.state);
		expect(third.collapsed).toBeNull();
		expect(third.state.selected).toBeNull();
	});
});

describe('focus', () => {
	it('is the selection, else the deepest expanded topic', () => {
		expect(focusOf(index, EMPTY_STATE)).toBeNull();
		expect(focusOf(index, { expanded: ['a', 'a1'], selected: null })).toBe('a1');
		expect(focusOf(index, { expanded: ['a'], selected: 'b' })).toBe('b');
	});
	it('rebuilds a state from a focus and ignores an unknown one', () => {
		expect(stateForFocus(index, 'a1x').expanded).toEqual(['a', 'a1']);
		expect(stateForFocus(index, 'nope')).toEqual(EMPTY_STATE);
		expect(stateForFocus(index, null)).toEqual(EMPTY_STATE);
	});
});

describe('zoomChanges', () => {
	const cut = cutOf(index, ['a']);
	const px = (id: string, radiusPx: number, visible = true) => ({ id, radiusPx, visible });
	it('expands a big bubble and collapses a small hull', () => {
		expect(zoomChanges(index, cut, [px('a1', 150), px('b', 30)]).expand).toEqual(['a1']);
		expect(zoomChanges(index, cut, [px('a', 40)]).collapse).toEqual(['a']);
	});
	it('keeps the band between the two thresholds as it is', () => {
		const changes = zoomChanges(index, cut, [px('a', 90), px('a1', 90)]);
		expect(changes).toEqual({ expand: [], collapse: [] });
	});
	it('opens only the focused bubble, one at a time, the biggest first', () => {
		const viewport = { width: 1000, height: 600 };
		const at = (id: string, radiusPx: number, cx: number, cy = 300) => ({
			id,
			radiusPx,
			visible: true,
			cx,
			cy
		});
		const roots = cutOf(index, []);
		// b is big but sits at the right edge; a is central
		expect(
			zoomChanges(index, roots, [at('a', 200, 500), at('b', 400, 950)], { viewport }).expand
		).toEqual(['a']);
		expect(
			zoomChanges(index, roots, [at('a', 200, 450), at('b', 300, 520)], { viewport }).expand
		).toEqual(['b']);
	});
	it('never opens a bubble by itself while the camera shows everything', () => {
		const roots = cutOf(index, []);
		const big = [{ id: 'a', radiusPx: 400, visible: true, cx: 500, cy: 300 }];
		const viewport = { width: 1000, height: 600, zoomedIn: false };
		expect(zoomChanges(index, roots, big, { viewport }).expand).toEqual([]);
		expect(
			zoomChanges(index, roots, big, { viewport: { ...viewport, zoomedIn: true } }).expand
		).toEqual(['a']);
	});
	it('ignores topics off screen and bubbles without children', () => {
		expect(zoomChanges(index, cut, [px('a1', 500, false), px('a2', 500)]).expand).toEqual([]);
	});
	it('reports only the outermost hull to collapse', () => {
		const deep = cutOf(index, ['a', 'a1']);
		const changes = zoomChanges(index, deep, [px('a', 30), px('a1', 20)]);
		expect(changes.collapse).toEqual(['a']);
	});
});
