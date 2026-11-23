<script lang="ts">
	import PaperList from '#lib/components/PaperList.svelte';
	import YearSparkline from '#lib/components/YearSparkline.svelte';
	import { resolve } from '$app/paths';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const venue = $derived(data.venue);
	const kind = $derived(venue.kind === 'book-series' ? 'book series' : venue.kind);
</script>

<svelte:head>
	<title>{venue.acronym}: {venue.name} · The FLAT Atlas</title>
	<meta
		name="description"
		content="{venue.name} ({venue.acronym}), a {kind} in formal languages and automata theory: {venue.n_works} papers in the atlas, {venue.first_year} to {venue.last_year ??
			'today'}."
	/>
</svelte:head>

<h1>{venue.acronym}</h1>
<p>{venue.name}</p>
<p class="muted">
	{kind} · {venue.first_year} to {venue.last_year ?? 'today'} · {venue.n_works} papers in the atlas
	{#if venue.homepage}
		·
		<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
		<a href={venue.homepage} rel="noopener noreferrer">website</a>
	{/if}
</p>

<h2>Papers per year</h2>
<YearSparkline points={venue.year_series.map((y) => ({ year: y.year, value: y.papers }))} />

<h2>Main topics</h2>
{#if venue.top_topics.length === 0}
	<p class="muted">No topics yet.</p>
{:else}
	<ul>
		{#each venue.top_topics as t (t.topic_id)}
			<li>
				<a href={resolve('/topic/[id]', { id: t.topic_id })}>{t.name}</a>
				<span class="muted">{t.papers} papers</span>
			</li>
		{/each}
	</ul>
{/if}

<h2>Most cited papers</h2>
<PaperList
	papers={venue.top_papers}
	initialSort="cited"
	emptyText="No papers yet."
	label="Most cited papers at {venue.acronym}"
/>
