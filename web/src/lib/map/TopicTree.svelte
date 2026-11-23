<script lang="ts">
	import { tick } from 'svelte';
	import { resolve } from '$app/paths';
	import { moveInTree, typeAhead, type TreeAction, type TreeRow } from './treeNav';

	/**
	 * The tree of the topics the map draws. It is the keyboard and screen-reader interface of the
	 * map (`variant="mirror"`: present for assistive technology and the keyboard, drawn off screen)
	 * and the list view (`variant="list"`: the same rows, shown). WAI-ARIA tree pattern with a
	 * roving tabindex.
	 */
	let {
		rows,
		current,
		selected = null,
		variant,
		onmove,
		onaction
	}: {
		rows: TreeRow[];
		/** The row that is the tab stop, null for the first one. */
		current: string | null;
		selected?: string | null;
		variant: 'mirror' | 'list';
		onmove: (id: string) => void;
		onaction: (action: TreeAction, id: string) => void;
	} = $props();

	const uid = $props.id();
	const tabStop = $derived(rows.some((r) => r.id === current) ? current : (rows[0]?.id ?? null));
	let typed = '';
	let typedTimer: ReturnType<typeof setTimeout> | undefined;

	async function focusRow(id: string) {
		await tick();
		document.getElementById(`${uid}-${id}`)?.focus();
	}

	function onkeydown(event: KeyboardEvent, id: string) {
		if (event.altKey || event.ctrlKey || event.metaKey) return;
		if (event.key.length === 1 && event.key !== ' ') {
			typed += event.key;
			clearTimeout(typedTimer);
			typedTimer = setTimeout(() => (typed = ''), 700);
			const hit = typeAhead(rows, id, typed);
			if (hit) {
				event.preventDefault();
				onmove(hit);
				void focusRow(hit);
			}
			return;
		}
		const move = moveInTree(rows, id, event.key);
		if (!move) return;
		event.preventDefault();
		if (move.focus !== id) {
			onmove(move.focus);
			void focusRow(move.focus);
		}
		if (move.action) onaction(move.action, move.focus);
	}
</script>

<ul
	role="tree"
	aria-label="Topics on the map"
	class:mirror={variant === 'mirror'}
	class:list={variant === 'list'}
>
	{#each rows as row (row.id)}
		<li
			id="{uid}-{row.id}"
			role="treeitem"
			aria-level={row.depth}
			aria-posinset={row.posInSet}
			aria-setsize={row.setSize}
			aria-expanded={row.hasChildren ? row.expanded : undefined}
			aria-selected={row.id === selected}
			tabindex={row.id === tabStop ? 0 : -1}
			style:--depth={row.depth - 1}
			class:has-children={row.hasChildren}
			class:open={row.expanded}
			onkeydown={(e) => onkeydown(e, row.id)}
			onfocus={() => onmove(row.id)}
			onclick={() => onaction(row.hasChildren ? 'toggle' : 'select', row.id)}
		>
			<span class="name">{row.name}</span>
			<span class="muted count">{row.paperCount} papers</span>
			{#if row.hasChildren}
				<span class="sr-only">
					{row.expanded ? 'expanded' : 'collapsed'}, subtopics
				</span>
			{/if}
			<a
				href={resolve('/topic/[id]', { id: row.id })}
				tabindex="-1"
				onclick={(e) => e.stopPropagation()}
				>Open topic page<span class="sr-only">: {row.name}</span></a
			>
		</li>
	{/each}
</ul>

<style>
	ul {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.mirror {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
	}

	.list li {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0.2rem 0.75rem;
		padding: 0.3rem 0.6rem 0.3rem calc(1.4rem + var(--depth) * 1.5rem);
		border-bottom: 1px solid var(--line);
		cursor: pointer;
		position: relative;
	}

	.list li.has-children::before {
		content: '▸';
		position: absolute;
		left: calc(0.5rem + var(--depth) * 1.5rem);
		color: var(--muted);
	}

	.list li.has-children.open::before {
		content: '▾';
	}

	.list li[aria-selected='true'] {
		background: var(--chip);
	}

	.list li:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}

	.list .name {
		font-weight: 600;
	}

	.list a {
		margin-left: auto;
		font-size: 0.85rem;
	}

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
	}

	.mirror a,
	.mirror .count {
		display: none;
	}
</style>
