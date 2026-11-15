<script lang="ts">
	import ConfidenceBadge from '#lib/components/ConfidenceBadge.svelte';
	import { resolve } from '$app/paths';
	import type { TopicEdge } from '#lib/data/index.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const page = $derived(data.page);
	const buildsOn = $derived(page.edges['builds-on'].filter((e) => e.direction === 'out'));
	const builtOnBy = $derived(page.edges['builds-on'].filter((e) => e.direction === 'in'));
	const maxPapers = $derived(Math.max(1, ...page.year_series.map((y) => y.papers)));
</script>

<svelte:head>
	<title>{page.topic.name} · The FLAT Atlas</title>
	<meta name="description" content={page.topic.description} />
</svelte:head>

{#snippet edgeList(edges: TopicEdge[])}
	{#if edges.length === 0}
		<p class="muted">None yet.</p>
	{:else}
		<ul>
			{#each edges as edge (edge.topic_id)}
				<li>
					<a href={resolve('/topic/[id]', { id: edge.topic_id })}>{edge.name}</a>
					<ConfidenceBadge value={edge.confidence} title="Edge confidence; weight {edge.weight}" />
				</li>
			{/each}
		</ul>
	{/if}
{/snippet}

<nav aria-label="Breadcrumb" class="crumbs">
	{#if page.parents.length === 0}
		<a href={resolve('/')}>Topics</a> › {page.topic.name}
	{:else}
		{#each page.parents as parent (parent.topic_id)}
			<div>
				<a href={resolve('/')}>Topics</a> ›
				<a href={resolve('/topic/[id]', { id: parent.topic_id })}>{parent.name}</a> ›
				{page.topic.name}
			</div>
		{/each}
	{/if}
</nav>

<h1>{page.topic.name}</h1>
<p>{page.topic.description}</p>
<p class="muted">{page.topic.paper_count} papers</p>

{#if page.children.length > 0}
	<h2>Subtopics</h2>
	<ul class="chips">
		{#each page.children as child (child.topic_id)}
			<li><a href={resolve('/topic/[id]', { id: child.topic_id })}>{child.name}</a></li>
		{/each}
	</ul>
{/if}

<h2>Related topics</h2>
<p class="muted">Topics that are often tagged on the same papers.</p>
{@render edgeList(page.edges.related)}

<h2>Builds on</h2>
<p class="muted">Topics whose papers this topic's papers cite.</p>
{@render edgeList(buildsOn)}

<h2>Built on by</h2>
<p class="muted">Topics whose papers cite this topic's papers.</p>
{@render edgeList(builtOnBy)}

<h2>Shared community</h2>
<p class="muted">Topics that many of the same authors work on.</p>
{@render edgeList(page.edges['shared-community'])}

<h2>Papers</h2>
<ul class="papers">
	{#each page.top_papers as paper (paper.work_id)}
		<li>
			<span>{paper.title}</span>
			<span class="muted">{paper.venue_acronym} {paper.year}</span>
			<ConfidenceBadge value={paper.confidence} title="Confidence of the topic tag" />
		</li>
	{/each}
</ul>

<h2>Key authors</h2>
<ul>
	{#each page.key_authors as author (author.author_id)}
		<li>{author.name}</li>
	{/each}
</ul>

<h2>Activity</h2>
<svg
	class="spark"
	viewBox="0 0 {page.year_series.length * 14} 40"
	role="img"
	aria-label="Papers per year: {page.year_series.map((y) => `${y.year}: ${y.papers}`).join(', ')}"
>
	{#each page.year_series as y, i (y.year)}
		<rect
			x={i * 14 + 2}
			y={40 - (y.papers / maxPapers) * 36}
			width="10"
			height={(y.papers / maxPapers) * 36}
		/>
	{/each}
</svg>
{#if page.year_series.length > 0}
	<p class="muted">
		{page.year_series[0].year} to {page.year_series[page.year_series.length - 1].year}
	</p>
{/if}

<style>
	.crumbs {
		font-size: 0.9rem;
		color: var(--muted);
	}

	.papers {
		padding-left: 1.1rem;
	}

	.papers li {
		margin: 0.35rem 0;
	}

	.spark {
		width: 100%;
		max-width: 28rem;
		height: 3.5rem;
		fill: var(--accent);
	}
</style>
