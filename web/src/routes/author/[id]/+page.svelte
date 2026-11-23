<script lang="ts">
	import PaperList from '#lib/components/PaperList.svelte';
	import YearSparkline from '#lib/components/YearSparkline.svelte';
	import { resolve } from '$app/paths';
	import { SvelteMap } from 'svelte/reactivity';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const author = $derived(data.author);
	const nameOf = $derived(new SvelteMap(data.topics.map((t) => [t.topic_id, t.name])));
	const topScore = $derived(Math.max(0.001, ...author.topics.map((t) => t.score)));
	const years = $derived.by(() => {
		const counts: Record<number, number> = {};
		for (const p of author.papers) counts[p.year] = (counts[p.year] ?? 0) + 1;
		return Object.entries(counts).map(([year, value]) => ({ year: Number(year), value }));
	});
	const topNames = $derived(
		author.topics
			.slice(0, 3)
			.map((t) => nameOf.get(t.topic_id) ?? t.topic_id)
			.join(', ')
	);
</script>

<svelte:head>
	<title>{author.display_name} · The FLAT Atlas</title>
	<meta
		name="description"
		content="{author.display_name}: {author.papers
			.length} papers in formal languages and automata theory{topNames
			? `, mostly on ${topNames}`
			: ''}."
	/>
</svelte:head>

<h1>{author.display_name}</h1>
{#if author.name_variants.length > 0}
	<p class="muted">Also written: {author.name_variants.join('; ')}</p>
{/if}
<p>
	{#if author.dblp_pid}<a href="https://dblp.org/pid/{author.dblp_pid}" rel="noopener noreferrer"
			>DBLP</a
		>{/if}
	{#if author.dblp_pid && author.orcid}
		·
	{/if}
	{#if author.orcid}<a href="https://orcid.org/{author.orcid}" rel="noopener noreferrer">ORCID</a
		>{/if}
	{#if !author.dblp_pid && !author.orcid}<span class="muted">No external profile is known.</span
		>{/if}
</p>

<h2>Topics</h2>
{#if author.topics.length === 0}
	<p class="muted">No topic profile: none of this author's papers has been classified yet.</p>
{:else}
	<ul class="profile">
		{#each author.topics as t (t.topic_id)}
			<li>
				<a href={resolve('/topic/[id]', { id: t.topic_id })}
					>{nameOf.get(t.topic_id) ?? t.topic_id}</a
				>
				<span class="bar" aria-hidden="true"
					><span style:width="{(t.score / topScore) * 100}%"></span></span
				>
				<span class="muted">weight {t.score.toFixed(1)}</span>
			</li>
		{/each}
	</ul>
	<p class="muted">
		The weight adds up the confidences of the author's papers in a topic (square-root scaled), so it
		is not a paper count.
	</p>
{/if}

<h2>Timeline</h2>
<YearSparkline points={years} />

<h2>Co-authors</h2>
{#if author.coauthors.length === 0}
	<p class="muted">No co-authors in the atlas.</p>
{:else}
	<ul class="coauthors">
		{#each author.coauthors as c (c.author_id)}
			<li>
				<a href={resolve('/author/[id]', { id: c.author_id })}>{c.name}</a>
				<span class="muted">{c.n_papers} paper{c.n_papers === 1 ? '' : 's'}</span>
			</li>
		{/each}
	</ul>
{/if}

<h2>Papers ({author.papers.length})</h2>
<PaperList
	papers={author.papers}
	initialSort="newest"
	emptyText="No papers."
	label="Papers by {author.display_name}"
/>

<style>
	.profile {
		padding: 0;
		list-style: none;
		display: grid;
		gap: 0.4rem;
	}

	.profile li {
		display: grid;
		grid-template-columns: minmax(10rem, 2fr) minmax(4rem, 1fr) auto;
		gap: 0.75rem;
		align-items: center;
	}

	.bar {
		display: block;
		height: 0.6rem;
		border-radius: 0.3rem;
		background: var(--chip);
	}

	.bar span {
		display: block;
		height: 100%;
		border-radius: 0.3rem;
		background: var(--accent);
	}

	.coauthors {
		columns: 15rem;
		padding-left: 1.1rem;
	}

	@media (max-width: 40rem) {
		.profile li {
			grid-template-columns: 1fr auto;
		}

		.bar {
			grid-column: 1 / -1;
			order: 3;
		}
	}
</style>
