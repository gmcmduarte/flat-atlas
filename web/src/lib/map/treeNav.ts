import { cutOf } from './visible';
import type { MapIndex } from './model';

/** One row of the tree that mirrors the map: every bubble and every expanded topic. */
export interface TreeRow {
	id: string;
	name: string;
	level: number;
	/** 1-based, as `aria-level`. */
	depth: number;
	parentId: string | null;
	posInSet: number;
	setSize: number;
	hasChildren: boolean;
	expanded: boolean;
	paperCount: number;
}

/** The rows in reading order: a topic, then (when expanded) its children. */
export function treeRows(index: MapIndex, expanded: Iterable<string>): TreeRow[] {
	const cut = cutOf(index, expanded);
	const open = new Set(cut.hulls);
	const rows: TreeRow[] = [];
	const visit = (id: string, depth: number, posInSet: number, setSize: number) => {
		const t = index.topics.get(id);
		if (!t) return;
		rows.push({
			id,
			name: t.name,
			level: t.level,
			depth,
			parentId: t.parentId,
			posInSet,
			setSize,
			hasChildren: t.children.length > 0,
			expanded: open.has(id),
			paperCount: t.paperCount
		});
		if (open.has(id)) {
			t.children.forEach((child, i) => visit(child, depth + 1, i + 1, t.children.length));
		}
	};
	index.roots.forEach((root, i) => visit(root, 1, i + 1, index.roots.length));
	return rows;
}

export type TreeAction = 'expand' | 'collapse' | 'open' | 'toggle' | 'select' | 'back';

export interface TreeMove {
	/** The row that has the focus afterwards. */
	focus: string;
	/** What the tree should do with the row that had it (or `focus` for `open`). */
	action: TreeAction | null;
}

/**
 * Keyboard behaviour of the tree (WAI-ARIA tree pattern): Up/Down move through the rows, Right
 * opens a closed topic or moves to its first child, Left closes an open one or moves to the
 * parent, Home/End jump, Enter opens the topic's page, Space toggles, Escape goes back.
 * Returns null for a key the tree does not handle.
 */
export function moveInTree(rows: TreeRow[], current: string, key: string): TreeMove | null {
	const at = rows.findIndex((r) => r.id === current);
	if (at < 0) return rows.length ? { focus: rows[0].id, action: null } : null;
	const row = rows[at];
	switch (key) {
		case 'ArrowDown':
			return { focus: rows[Math.min(at + 1, rows.length - 1)].id, action: null };
		case 'ArrowUp':
			return { focus: rows[Math.max(at - 1, 0)].id, action: null };
		case 'Home':
			return { focus: rows[0].id, action: null };
		case 'End':
			return { focus: rows[rows.length - 1].id, action: null };
		case 'ArrowRight':
			if (!row.hasChildren) return { focus: row.id, action: null };
			if (!row.expanded) return { focus: row.id, action: 'expand' };
			return { focus: rows[at + 1].id, action: null };
		case 'ArrowLeft':
			if (row.expanded) return { focus: row.id, action: 'collapse' };
			return {
				focus: row.parentId && rows.some((r) => r.id === row.parentId) ? row.parentId : row.id,
				action: null
			};
		case 'Enter':
			return { focus: row.id, action: 'open' };
		case ' ':
			return { focus: row.id, action: row.hasChildren ? 'toggle' : null };
		case 'Escape':
			return { focus: row.id, action: 'back' };
		default:
			return null;
	}
}

/** Type-ahead: the next row after `current` whose name starts with `typed` (wraps around). */
export function typeAhead(rows: TreeRow[], current: string, typed: string): string | null {
	const needle = typed.toLowerCase();
	if (!needle) return null;
	const start = rows.findIndex((r) => r.id === current);
	for (let step = 1; step <= rows.length; step++) {
		const row = rows[(start + step + (typed.length > 1 ? -1 : 0) + rows.length) % rows.length];
		if (row.name.toLowerCase().startsWith(needle)) return row.id;
	}
	return null;
}
