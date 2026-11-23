<script lang="ts">
	import ConfidenceBadge from '#lib/components/ConfidenceBadge.svelte';
	import PaperList from '#lib/components/PaperList.svelte';
	import { resolve } from '$app/paths';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const work = $derived(data.work);
	const direct = $derived(work.tags.filter((t) => !t.derived));
	const broader = $derived(work.tags.filter((t) => t.derived));
	const names = $derived(work.authors.map((a) => a.name).join(', '));
	const links = $derived(
		[
			['DOI', work.links.doi],
			['DBLP', work.links.dblp],
			['OpenAlex', work.links.openalex],
			['Open-access copy', work.links.open_access]
		].filter((l): l is [string, string] => l[1] !== null)
	);
	const description = $derived(
		`${names ? `${names}. ` : ''}${work.venue.acronym} ${work.year}.` +
			(direct.length > 0 ? ` Topics: ${direct.map((t) => t.topic_name).join(', ')}.` : '')
	);
</script>

<svelte:head>
	<title>{work.title} · The FLAT Atlas</title>
	<meta name="description" content={description} />
</svelte:head>

<h1>{work.title}</h1>
<ul class="authors" aria-label="Authors">
	{#each work.authors as author (author.author_id)}
		<li><a href={resolve('/author/[id]', { id: author.author_id })}>{author.name}</a></li>
	{/each}
</ul>
<p class="muted">
	{#if work.venue.venue_id}
		<a href={resolve('/venue/[id]', { id: work.venue.venue_id })}>{work.venue.acronym}</a>
	{:else}
		{work.venue.acronym}
	{/if}
	{work.year} · {work.work_type.replace(/-/g, ' ')} · {work.cited_by_count} citation{work.cited_by_count ===
	1
		? ''
		: 's'}
</p>

<h2>Topics</h2>
{#if work.tag_status === 'untagged'}
	<p>Not classified yet: the tagger found no topic for this paper.</p>
{:else}
	{#if work.tag_status === 'low_confidence'}
		<p class="muted">
			Weak match: the tagger is not sure which topic this paper belongs to. The topic below is its
			best guess.
		</p>
	{/if}
	<ul class="tags">
		{#each direct as tag (tag.topic_id)}
			<li>
				<a href={resolve('/topic/[id]', { id: tag.topic_id })}>{tag.topic_name}</a>
				{#if tag.is_primary}<span class="muted">(main topic)</span>{/if}
				<ConfidenceBadge value={tag.confidence} provenance={tag.provenance} showExplanation />
			</li>
		{/each}
	</ul>
	{#if broader.length > 0}
		<details>
			<summary>Broader topics ({broader.length})</summary>
			<p class="muted">
				Parents of the topics above: the paper counts in them through its subtopic.
			</p>
			<ul class="tags">
				{#each broader as tag (tag.topic_id)}
					<li>
						<a href={resolve('/topic/[id]', { id: tag.topic_id })}>{tag.topic_name}</a>
						<ConfidenceBadge
							value={tag.confidence}
							title="Inherited: this paper is tagged with a subtopic of {tag.topic_name}"
						/>
					</li>
				{/each}
			</ul>
		</details>
	{/if}
{/if}

{#if work.versions.length > 1}
	<h2>Versions</h2>
	<ul>
		{#each work.versions as v, i (i)}
			<li>
				{#if v.url}
					<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
					<a href={v.url} rel="noopener noreferrer">{v.venue_acronym} {v.year}</a>
				{:else}{v.venue_acronym} {v.year}{/if}
				{#if v.volume}<span class="muted">vol. {v.volume}</span>{/if}
				{#if v.pages}<span class="muted">pp. {v.pages}</span>{/if}
				{#if i === 0}<span class="muted">(the version shown above)</span>{/if}
			</li>
		{/each}
	</ul>
{/if}

<h2>Links</h2>
{#if links.length === 0}
	<p class="muted">No external links are known for this paper.</p>
{:else}
	<ul>
		{#each links as [label, href] (label)}
			<li>
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
				<a {href} rel="noopener noreferrer">{label}</a>
			</li>
		{/each}
	</ul>
{/if}

<h2>References in the atlas ({work.references.length})</h2>
<PaperList
	papers={work.references}
	initialSort="cited"
	emptyText="No references to other papers in the atlas are known."
	label="References"
/>

<h2>Cited by, in the atlas ({work.cited_by.length})</h2>
<PaperList
	papers={work.cited_by}
	initialSort="cited"
	emptyText="No paper in the atlas is known to cite this one."
	label="Cited by"
/>

<style>
	.authors {
		margin: 0.2rem 0;
		padding: 0;
		list-style: none;
		font-size: 1.05rem;
	}

	.authors li {
		display: inline;
	}

	.authors li:not(:last-child)::after {
		content: ', ';
	}

	.tags {
		padding: 0;
		list-style: none;
		display: grid;
		gap: 0.8rem;
	}
</style>
