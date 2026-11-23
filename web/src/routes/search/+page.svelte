<script lang="ts">
	import { browserDataSource, type SearchResults } from '#lib/data/index.js';
	import { MIN_QUERY } from '#lib/search/limits.js';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';

	const MORE = 25;

	const q = $derived(page.url.searchParams.get('q')?.trim() ?? '');
	let phase = $state<'idle' | 'loading' | 'error'>('idle');
	let results = $state<SearchResults | null>(null);
	let latest = 0;

	$effect(() => {
		const query = q;
		const mine = ++latest;
		if (query.length < MIN_QUERY) {
			results = null;
			phase = 'idle';
			return;
		}
		phase = 'loading';
		browserDataSource()
			.search(query, MORE)
			.then((found) => {
				if (mine !== latest) return;
				results = found;
				phase = 'idle';
			})
			.catch(() => {
				if (mine !== latest) return;
				results = null;
				phase = 'error';
			});
	});

	const total = $derived(
		results
			? results.topics.length +
					results.authors.length +
					results.venues.length +
					results.works.length
			: 0
	);
</script>

<svelte:head>
	<title>{q ? `Search: ${q}` : 'Search'} · The FLAT Atlas</title>
	<meta name="description" content="Search topics, authors, venues and papers in the FLAT Atlas." />
	<meta name="robots" content="noindex" />
</svelte:head>

<h1>Search</h1>
{#if q.length < MIN_QUERY}
	<p class="muted">Type at least {MIN_QUERY} letters in the search box above.</p>
{:else if phase === 'error'}
	<p>The search index could not be loaded. Reload the page to try again.</p>
{:else if phase === 'loading' && !results}
	<p class="muted" role="status">Searching for "{q}"…</p>
{:else if results}
	<p class="muted" role="status">
		{total === 0 ? `No results for "${q}".` : `Results for "${q}".`}
	</p>
	{#if results.topics.length > 0}
		<h2>Topics ({results.topics.length})</h2>
		<ul>
			{#each results.topics as t (t.topic_id)}
				<li><a href={resolve('/topic/[id]', { id: t.topic_id })}>{t.name}</a></li>
			{/each}
		</ul>
	{/if}
	{#if results.authors.length > 0}
		<h2>Authors ({results.authors.length})</h2>
		<ul>
			{#each results.authors as a (a.author_id)}
				<li><a href={resolve('/author/[id]', { id: a.author_id })}>{a.name}</a></li>
			{/each}
		</ul>
	{/if}
	{#if results.venues.length > 0}
		<h2>Venues ({results.venues.length})</h2>
		<ul>
			{#each results.venues as v (v.venue_id)}
				<li>
					<a href={resolve('/venue/[id]', { id: v.venue_id })}>{v.acronym}</a>
					<span class="muted">{v.name}</span>
				</li>
			{/each}
		</ul>
	{/if}
	{#if results.works.length > 0}
		<h2>Papers ({results.works.length})</h2>
		<ul>
			{#each results.works as w (w.work_id)}
				<li>
					<a href={resolve('/paper/[id]', { id: w.work_id })}>{w.title}</a>
					<span class="muted">{w.year}</span>
				</li>
			{/each}
		</ul>
	{/if}
	{#if results.topics.length >= MORE || results.authors.length >= MORE || results.works.length >= MORE}
		<p class="muted">
			Only the {MORE} best matches of each kind are shown. Add words to narrow it down.
		</p>
	{/if}
{/if}
