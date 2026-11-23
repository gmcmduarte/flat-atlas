import { describe, expect, it } from 'vitest';
import { sampleIndex } from './testIndex';
import { moveInTree, treeRows, typeAhead } from './treeNav';
import { readFocus, withFocus } from './urlState';

const index = sampleIndex();

describe('treeRows', () => {
	it('lists the bubbles and the open topics in reading order with ARIA numbers', () => {
		const rows = treeRows(index, ['a']);
		expect(rows.map((r) => r.id)).toEqual(['a', 'a1', 'a2', 'b']);
		expect(rows[0]).toMatchObject({ depth: 1, posInSet: 1, setSize: 2, expanded: true });
		expect(rows[1]).toMatchObject({
			depth: 2,
			posInSet: 1,
			setSize: 2,
			hasChildren: true,
			expanded: false
		});
		expect(rows[2]).toMatchObject({ hasChildren: false });
	});
});

describe('moveInTree', () => {
	const rows = treeRows(index, ['a']);
	it('moves with the arrows and stops at the ends', () => {
		expect(moveInTree(rows, 'a', 'ArrowDown')).toEqual({ focus: 'a1', action: null });
		expect(moveInTree(rows, 'a', 'ArrowUp')).toEqual({ focus: 'a', action: null });
		expect(moveInTree(rows, 'b', 'ArrowDown')).toEqual({ focus: 'b', action: null });
		expect(moveInTree(rows, 'a1', 'End')?.focus).toBe('b');
		expect(moveInTree(rows, 'b', 'Home')?.focus).toBe('a');
	});
	it('opens with Right, then enters the first child; closes with Left, then goes to the parent', () => {
		expect(moveInTree(rows, 'b', 'ArrowRight')).toEqual({ focus: 'b', action: 'expand' });
		expect(moveInTree(rows, 'a', 'ArrowRight')).toEqual({ focus: 'a1', action: null });
		expect(moveInTree(rows, 'a2', 'ArrowRight')).toEqual({ focus: 'a2', action: null });
		expect(moveInTree(rows, 'a', 'ArrowLeft')).toEqual({ focus: 'a', action: 'collapse' });
		expect(moveInTree(rows, 'a1', 'ArrowLeft')).toEqual({ focus: 'a', action: null });
		expect(moveInTree(rows, 'b', 'ArrowLeft')).toEqual({ focus: 'b', action: null });
	});
	it('maps Enter, Space and Escape to actions and ignores other keys', () => {
		expect(moveInTree(rows, 'a1', 'Enter')?.action).toBe('open');
		expect(moveInTree(rows, 'a1', ' ')?.action).toBe('toggle');
		expect(moveInTree(rows, 'a2', ' ')?.action).toBeNull();
		expect(moveInTree(rows, 'a1', 'Escape')?.action).toBe('back');
		expect(moveInTree(rows, 'a1', 'x')).toBeNull();
	});
});

describe('typeAhead', () => {
	const rows = treeRows(index, ['a']);
	it('finds the next row starting with the typed letters and wraps', () => {
		expect(typeAhead(rows, 'a', 'a')).toBe('a1');
		expect(typeAhead(rows, 'b', 'a')).toBe('a');
		expect(typeAhead(rows, 'a', 'a2')).toBe('a2');
		expect(typeAhead(rows, 'a', 'zz')).toBeNull();
	});
});

describe('url state', () => {
	it('reads a focus that is on the map and ignores others', () => {
		expect(readFocus('?focus=a1', index)).toBe('a1');
		expect(readFocus('?focus=nope', index)).toBeNull();
		expect(readFocus('', index)).toBeNull();
	});
	it('sets and removes the focus and keeps the rest of the URL', () => {
		const url = new URL('http://x/flat-atlas/?q=1#top');
		const set = withFocus(url, 'a1');
		expect(set.search).toBe('?q=1&focus=a1');
		expect(set.hash).toBe('#top');
		expect(withFocus(set, null).search).toBe('?q=1');
		expect(url.search).toBe('?q=1');
	});
});
