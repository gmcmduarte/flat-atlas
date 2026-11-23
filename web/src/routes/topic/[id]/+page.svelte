<script lang="ts">
	import ConfidenceBadge from '#lib/components/ConfidenceBadge.svelte';
	import PaperList from '#lib/components/PaperList.svelte';
	import TopicChips from '#lib/components/TopicChips.svelte';
	import YearSparkline from '#lib/components/YearSparkline.svelte';
	import { ancestorPaths } from '#lib/topics.js';
	import { resolve } from '$app/paths';
	import type { TopicEdge } from '#lib/data/index.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const page = $derived(data.page);
	const topic = $derived(page.topic);
	const paths = $derived(ancestorPaths(data.topics, topic.topic_id));
	const buildsOn = $derived(page.edges['builds-on'].filter((e) => e.direction === 'out'));
	const builtOnBy = $derived(page.edges['builds-on'].filter((e) => e.direction === 'in'));
	const shownNormal = $derived(page.top_papers.filter((p) => !p.low_confidence).length);
	const shownWeak = $derived(page.top_papers.length - shownNormal);

	const blurb = $derived(
		topic.description.length > 150 ? `${topic.description.slice(0, 147)}…` : topic.description
	);
</script>

<svelte:head>
	<title>{topic.name} · The FLAT Atlas</title>
	<meta
		name="description"
		content="{blurb} {topic.paper_count} papers in the atlas, with related topics and key authors."
	/>
</svelte:head>

{#snippet edgeList(edges: TopicEdge[], what: string, empty: string)}
	{#if edges.length === 0}
		<p class="muted">{empty}</p>
	{:else}
		<ul aria-label={what}>
			{#each edges as edge (edge.topic_id)}
				<li>
					<a href={resolve('/topic/[id]', { id: edge.topic_id })}>{edge.name}</a>
					<ConfidenceBadge
						value={edge.confidence}
						title="{what}: confidence {Math.round(edge.confidence * 100)}% (strength {edge.weight})"
					/>
				</li>
			{/each}
		</ul>
	{/if}
{/snippet}

<nav aria-label="Breadcrumb" class="crumbs">
	{#if paths.length === 0}
		<a href={resolve('/')}>Topics</a> › <span aria-current="page">{topic.name}</span>
	{:else}
		<ol>
			{#each paths as path (path.map((t) => t.topic_id).join('>'))}
				<li>
					<a href={resolve('/')}>Topics</a>
					{#each path as step (step.topic_id)}
						› <a href={resolve('/topic/[id]', { id: step.topic_id })}>{step.name}</a>
					{/each}
					› <span aria-current="page">{topic.name}</span>
				</li>
			{/each}
		</ol>
	{/if}
</nav>

<h1>{topic.name}</h1>
<p>{topic.description}</p>
<p class="muted">
	{topic.paper_count} papers{#if topic.n_low_confidence > 0}
		and {topic.n_low_confidence} weak match{topic.n_low_confidence === 1 ? '' : 'es'}{/if}
	· topic tags are assigned automatically and each carries a confidence.
</p>

{#if page.children.length > 0}
	<h2>Subtopics</h2>
	<TopicChips topics={page.children} label="Subtopics of {topic.name}" />
{/if}

<h2>Papers</h2>
{#if topic.paper_count > shownNormal || topic.n_low_confidence > shownWeak}
	<p class="muted">
		{#if topic.paper_count > shownNormal}
			Showing the {shownNormal} best matches of {topic.paper_count} papers; the sort order applies to
			these.
		{/if}
		{#if topic.n_low_confidence > shownWeak}
			{topic.n_low_confidence - shownWeak} weak match{topic.n_low_confidence - shownWeak === 1
				? ' is'
				: 'es are'} not listed.
		{/if}
	</p>
{/if}
<PaperList
	papers={page.top_papers}
	initialSort="relevance"
	emptyText="No papers in this topic yet."
	label="Papers on {topic.name}"
/>

<h2>Links to other topics</h2>
<p class="muted">
	Three kinds of link, each measured differently: the confidence of one kind cannot be compared with
	the confidence of another.
</p>
<div class="two-col">
	<section class="panel" aria-labelledby="related">
		<h3 id="related">Related topics</h3>
		<p class="muted">
			Often tagged on the same papers. Confidence: share of resamplings of the papers in which the
			link stays.
		</p>
		{@render edgeList(
			page.edges.related,
			'Related topics',
			'No topic shares enough papers with this one.'
		)}
	</section>

	<section class="panel" aria-labelledby="builds">
		<h3 id="builds">Builds on, built on by</h3>
		<p class="muted">
			Citations that run mostly one way. Confidence: one minus the p-value of a permutation test.
			Few such links exist in the pilot, so many topics have none.
		</p>
		<h4>This topic builds on</h4>
		{@render edgeList(
			buildsOn,
			'Topics this topic builds on',
			'None found: no topic is cited by this topic’s papers clearly more than chance.'
		)}
		<h4>Built on by</h4>
		{@render edgeList(
			builtOnBy,
			'Topics that build on this topic',
			'None found: no topic cites this topic’s papers clearly more than chance.'
		)}
	</section>

	<section class="panel" aria-labelledby="community">
		<h3 id="community">Shared community</h3>
		<p class="muted">
			Many of the same authors work on both. Confidence: share of resamplings of the authors in
			which the link stays.
		</p>
		{@render edgeList(
			page.edges['shared-community'],
			'Topics with a shared community',
			'No topic shares enough authors with this one.'
		)}
	</section>
</div>

<h2>Key authors</h2>
{#if page.key_authors.length === 0}
	<p class="muted">No authors yet.</p>
{:else}
	<ul class="authors">
		{#each page.key_authors as author (author.author_id)}
			<li><a href={resolve('/author/[id]', { id: author.author_id })}>{author.name}</a></li>
		{/each}
	</ul>
{/if}

<h2>Activity</h2>
<YearSparkline points={page.year_series.map((y) => ({ year: y.year, value: y.papers }))} />

<style>
	.crumbs {
		font-size: 0.9rem;
		color: var(--muted);
	}

	.crumbs ol {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	h3 {
		margin: 1rem 0 0.2rem;
		font-size: 1.05rem;
	}

	h4 {
		margin: 0.8rem 0 0.1rem;
		font-size: 0.95rem;
	}

	.authors {
		columns: 14rem;
		padding-left: 1.1rem;
	}
</style>
