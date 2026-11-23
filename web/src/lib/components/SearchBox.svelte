<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { browserDataSource, type SearchResults } from '#lib/data/index.js';
	import { MIN_QUERY } from '#lib/search/limits.js';

	/** The header search: a combobox with the best few results per group (PLAN §11.3). */

	const PER_GROUP = 4;
	const listId = $props.id();

	interface Option {
		id: string;
		group: string;
		text: string;
		detail: string;
		href: string;
	}

	let query = $state('');
	let open = $state(false);
	let active = $state(-1);
	let status = $state<'idle' | 'loading' | 'error'>('idle');
	let results = $state<SearchResults | null>(null);
	let latest = 0;

	const trimmed = $derived(query.trim());
	const allHref = $derived(`${resolve('/search')}?q=${encodeURIComponent(trimmed)}`);

	const options = $derived.by<Option[]>(() => {
		if (!results) return [];
		const out: Option[] = [];
		for (const t of results.topics) {
			out.push({
				id: `${listId}-t-${t.topic_id}`,
				group: 'Topics',
				text: t.name,
				detail: '',
				href: resolve('/topic/[id]', { id: t.topic_id })
			});
		}
		for (const a of results.authors) {
			out.push({
				id: `${listId}-a-${a.author_id}`,
				group: 'Authors',
				text: a.name,
				detail: '',
				href: resolve('/author/[id]', { id: a.author_id })
			});
		}
		for (const v of results.venues) {
			out.push({
				id: `${listId}-v-${v.venue_id}`,
				group: 'Venues',
				text: `${v.acronym} · ${v.name}`,
				detail: '',
				href: resolve('/venue/[id]', { id: v.venue_id })
			});
		}
		for (const w of results.works) {
			out.push({
				id: `${listId}-w-${w.work_id}`,
				group: 'Papers',
				text: w.title,
				detail: String(w.year),
				href: resolve('/paper/[id]', { id: w.work_id })
			});
		}
		return out;
	});
	const groups = $derived(
		['Topics', 'Authors', 'Venues', 'Papers']
			.map((name) => ({ name, items: options.filter((o) => o.group === name) }))
			.filter((g) => g.items.length > 0)
	);
	/** The options in screen order, then the "all results" row. */
	const ordered = $derived(groups.flatMap((g) => g.items));
	const lastIndex = $derived(ordered.length); // the "see all" row
	const activeId = $derived(
		active >= 0 && active < ordered.length
			? ordered[active].id
			: active === lastIndex && ordered.length > 0
				? `${listId}-all`
				: undefined
	);
	const summary = $derived(
		status === 'loading'
			? 'Searching…'
			: status === 'error'
				? 'Search is not available: the search index could not be loaded.'
				: trimmed.length < MIN_QUERY
					? ''
					: ordered.length === 0
						? `No results for "${trimmed}".`
						: `${ordered.length} results; use the up and down arrow keys.`
	);

	async function run() {
		const q = query.trim();
		const mine = ++latest;
		active = -1;
		if (q.length < MIN_QUERY) {
			results = null;
			status = 'idle';
			return;
		}
		status = 'loading';
		try {
			const found = await browserDataSource().search(q, PER_GROUP);
			if (mine !== latest) return;
			results = found;
			status = 'idle';
		} catch {
			if (mine !== latest) return;
			results = null;
			status = 'error';
		}
	}

	function go(href: string) {
		open = false;
		query = '';
		results = null;
		active = -1;
		// `href` is always the result of `resolve()` (the options and `allHref`).
		// eslint-disable-next-line svelte/no-navigation-without-resolve
		void goto(href);
	}

	function onkeydown(e: KeyboardEvent) {
		const rows = ordered.length > 0 ? ordered.length + 1 : 0;
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			open = true;
			if (rows > 0) active = (active + 1) % rows;
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			if (rows > 0) active = (active - 1 + rows) % rows;
		} else if (e.key === 'Enter') {
			e.preventDefault();
			if (active >= 0 && active < ordered.length) go(ordered[active].href);
			else if (trimmed.length >= MIN_QUERY) go(allHref);
		} else if (e.key === 'Escape') {
			if (open) {
				e.preventDefault();
				open = false;
				active = -1;
			}
		}
	}

	function onfocusout(e: FocusEvent) {
		const next = e.relatedTarget as Node | null;
		if (!next || !(e.currentTarget as HTMLElement).contains(next)) open = false;
	}

	const expanded = $derived(open && trimmed.length >= MIN_QUERY);
</script>

<form role="search" onsubmit={(e) => e.preventDefault()} {onfocusout} class="search">
	<label class="sr-only" for="{listId}-input">Search topics, authors, venues and papers</label>
	<input
		id="{listId}-input"
		type="search"
		placeholder="Search topics, authors, papers"
		autocomplete="off"
		spellcheck="false"
		role="combobox"
		aria-autocomplete="list"
		aria-expanded={expanded}
		aria-controls={listId}
		aria-activedescendant={activeId}
		bind:value={query}
		oninput={() => {
			open = true;
			void run();
		}}
		onfocus={() => (open = true)}
		{onkeydown}
	/>
	<p class="sr-only" role="status">{summary}</p>
	<div id={listId} role="listbox" aria-label="Search results" class="results" hidden={!expanded}>
		{#if summary && ordered.length === 0}
			<p class="note">{summary}</p>
		{/if}
		{#each groups as group (group.name)}
			<div role="group" aria-label={group.name}>
				<div class="group" aria-hidden="true">{group.name}</div>
				{#each group.items as option (option.id)}
					<!-- svelte-ignore a11y_click_events_have_key_events -->
					<div
						id={option.id}
						role="option"
						tabindex="-1"
						aria-selected={ordered[active]?.id === option.id}
						class="option"
						class:active={ordered[active]?.id === option.id}
						onmousedown={(e) => e.preventDefault()}
						onclick={() => go(option.href)}
					>
						<span>{option.text}</span>
						{#if option.detail}<span class="muted">{option.detail}</span>{/if}
					</div>
				{/each}
			</div>
		{/each}
		{#if ordered.length > 0}
			<!-- svelte-ignore a11y_click_events_have_key_events -->
			<div
				id="{listId}-all"
				role="option"
				tabindex="-1"
				aria-selected={active === lastIndex}
				class="option all"
				class:active={active === lastIndex}
				onmousedown={(e) => e.preventDefault()}
				onclick={() => go(allHref)}
			>
				See all results for "{trimmed}"
			</div>
		{/if}
	</div>
</form>

<style>
	.search {
		position: relative;
		flex: 1 1 16rem;
		max-width: 28rem;
	}

	input {
		box-sizing: border-box;
		width: 100%;
		padding: 0.4rem 0.7rem;
		border: 1px solid var(--muted);
		border-radius: 0.4rem;
		background: var(--chip);
		color: inherit;
		font: inherit;
	}

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
	}

	.results {
		position: absolute;
		z-index: 10;
		left: 0;
		right: 0;
		top: calc(100% + 0.25rem);
		max-height: 70vh;
		overflow-y: auto;
		border: 1px solid var(--line);
		border-radius: 0.4rem;
		background: var(--bg);
		box-shadow: 0 0.5rem 1.5rem rgb(0 0 0 / 0.18);
	}

	.group {
		padding: 0.4rem 0.7rem 0.1rem;
		font-size: 0.75rem;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--muted);
	}

	.option {
		display: flex;
		justify-content: space-between;
		gap: 0.75rem;
		padding: 0.35rem 0.7rem;
		cursor: pointer;
	}

	.option.active,
	.option:hover {
		background: var(--chip);
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}

	.all {
		border-top: 1px solid var(--line);
		color: var(--accent);
	}

	.note {
		margin: 0;
		padding: 0.6rem 0.7rem;
	}
</style>
