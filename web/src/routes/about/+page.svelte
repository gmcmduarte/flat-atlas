<script lang="ts">
	import ExternalLink from '#lib/components/ExternalLink.svelte';
	import { resolve } from '$app/paths';
	import { REPO_URL } from '#lib/site.js';
	import { formatDate, venueSeries } from '#lib/venues.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const meta = $derived(data.meta);
	const series = $derived(meta ? venueSeries(meta.venues) : []);
	const fromYear = $derived(
		meta && meta.venues.length > 0 ? Math.min(...meta.venues.map((v) => v.first_year)) : null
	);
</script>

<svelte:head>
	<title>About · The FLAT Atlas</title>
	<meta
		name="description"
		content="The FLAT Atlas is an open map of formal languages and automata theory: topics, papers, authors and venues. What the pilot covers, what it does not, and who runs it."
	/>
</svelte:head>

<article class="prose">
	<h1>About</h1>
	<p class="lead">
		The FLAT Atlas is an open map of <strong>formal languages and automata theory</strong>. It links
		topics, papers, authors and venues, so that you can start from a general topic and move to the
		specific ones, sideways to related ones, and to the papers and people behind them. The aim is
		the whole field, from the 1950s to today.
	</p>

	<h2>What is in the pilot</h2>
	{#if meta?.fixture}
		<p class="note">
			This copy of the site shows a small invented data set used for development, not the real
			corpus.
		</p>
	{:else if meta}
		<p>
			This is a <strong>pilot</strong>. Release {meta.release} ({formatDate(meta.date)}) holds
			{meta.works.toLocaleString('en')} papers from {series.length} conference series, {meta.venues
				.length}
			venues in all:
		</p>
		<ul>
			{#each series as s (s.current.venue_id)}
				<li>
					<a href={resolve('/venue/[id]', { id: s.current.venue_id })}>{s.current.acronym}</a>,
					{s.current.name}
					{#if s.predecessors.length > 0}
						(continues
						{#each s.predecessors as p, i (p.venue_id)}{i > 0 ? ', ' : ''}<a
								href={resolve('/venue/[id]', { id: p.venue_id })}>{p.acronym}</a
							>{/each})
					{/if}
				</li>
			{/each}
		</ul>
		<p>
			The papers date from {fromYear} onwards. Everything before that, every other conference and every
			journal is <strong>not in the atlas yet</strong>: what you see is a small, early slice of the
			field, chosen to prove the whole chain from sources to map. The topic list has
			{meta.topics} topics.
		</p>
	{/if}

	<h2>What it is, and what it is not</h2>
	<ul>
		<li>
			It stores <strong>metadata and links only</strong>: titles, authors, years, venues, and links
			to the DOI, DBLP and OpenAlex. It never stores or shows full texts.
		</li>
		<li>
			It does <strong>not show abstracts</strong> or publisher summaries. They are used on one computer
			to help decide a paper's topics, and are not published.
		</li>
		<li>
			Topics are assigned to papers <strong>automatically</strong>. Every assignment shows a
			confidence and how it was made, and some are wrong.
			<a href={resolve('/methods')}>The Methods page</a> says how, and how often.
		</li>
		<li>
			It is not a ranking of people or venues and it is not a bibliography you should cite instead
			of the papers.
		</li>
	</ul>

	<h2>Corrections and suggestions</h2>
	<p>
		Every topic, paper, author and venue page ends with a <em>Suggest a change</em> section. Its links
		open a form on GitHub with the page's details already filled in: a wrong topic, a missing paper, two
		author pages that are one person, a new topic, a fact about a venue. You need a free GitHub account,
		and what you write is public. Corrections go into the code, the topic list or the settings and the
		data is rebuilt; individual tags are not edited by hand.
	</p>

	<h2>Who and how</h2>
	<p>
		The atlas is built and maintained by Guilherme Duarte as an open project with no budget: free
		data sources, free software, and a laptop. The pipeline and this site are open source at
		<ExternalLink href={REPO_URL}>github.com/gmcmduarte/flat-atlas</ExternalLink> (code: MIT; data: CC
		BY 4.0).
	</p>
	<p>
		See <a href={resolve('/sources')}>Sources</a> for where the data comes from and under which
		licences, and <a href={resolve('/cite')}>Cite</a> for how to refer to the atlas.
	</p>
</article>
