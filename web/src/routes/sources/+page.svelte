<script lang="ts">
	import { resolve } from '$app/paths';
	import { formatDate } from '#lib/venues.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const meta = $derived(data.meta);
	// The key names of `source_fetch_dates` in meta.json, in the order the page lists them.
	const FETCHED: [string, string][] = [
		['dblp-dump', 'DBLP (XML dump)'],
		['openalex', 'OpenAlex'],
		['crossref', 'Crossref'],
		['semanticscholar', 'Semantic Scholar']
	];
	const dates = $derived(meta?.source_fetch_dates ?? {});
</script>

<svelte:head>
	<title>Sources · The FLAT Atlas</title>
	<meta
		name="description"
		content="Where the data of the FLAT Atlas comes from, what is taken from each source, under which licence, and what the atlas does and does not store or show."
	/>
</svelte:head>

<article class="prose">
	<h1>Sources</h1>
	<p class="lead">
		The atlas is built from open bibliographic sources. It stores and shows metadata and links, and
		it adds its own derived data: topic assignments, topic links and the map.
	</p>

	<h2>The sources</h2>
	<div class="scroll">
		<table>
			<caption class="sr-only">Sources, what is taken from them and their licences</caption>
			<thead>
				<tr>
					<th scope="col">Source</th>
					<th scope="col">What the atlas takes</th>
					<th scope="col">Licence</th>
				</tr>
			</thead>
			<tbody>
				<tr>
					<th scope="row"><a href="https://dblp.org">DBLP</a></th>
					<td>
						The list of venues, proceedings and papers; titles, authors, years, DOI links; author
						identifiers. Read from DBLP's XML dump.
					</td>
					<td>CC0 1.0</td>
				</tr>
				<tr>
					<th scope="row"><a href="https://openalex.org">OpenAlex</a></th>
					<td>
						Citation links and reference lists; topic hints; the titles of cited works; open-access
						links.
					</td>
					<td>CC0</td>
				</tr>
				<tr>
					<th scope="row"><a href="https://www.crossref.org">Crossref</a></th>
					<td>DOI metadata (publication details) and reference lists.</td>
					<td>
						Bibliographic metadata, which Crossref does not claim copyright in; abstracts that
						publishers deposit are not used on this site
					</td>
				</tr>
				<tr>
					<th scope="row"><a href="https://www.semanticscholar.org">Semantic Scholar</a></th>
					<td>
						Paper vectors (SPECTER2 embeddings) and identifiers, used to measure similarity between
						papers. Short automatic summaries (TLDRs) were read locally and are not shown.
					</td>
					<td>
						Data: ODC-BY 1.0 (attribution required); embeddings: Apache 2.0. Please cite Kinney et
						al. 2023 (below).
					</td>
				</tr>
				<tr>
					<th scope="row"
						><a href="https://dl.acm.org/ccs">ACM Computing Classification System</a></th
					>
					<td
						>One of several inputs when the topic list was drafted. No part of it is shown or
						redistributed.</td
					>
					<td>
						ACM keeps the copyright and states that the system is free to use for educational and
						research purposes
					</td>
				</tr>
			</tbody>
		</table>
	</div>

	<h3>Attribution</h3>
	<p>
		This site uses data from <a href="https://www.semanticscholar.org">Semantic Scholar</a>, the
		Allen Institute for AI's open scholarly platform. When you use Semantic Scholar data, please
		cite: Kinney, R. et al. (2023), <em>The Semantic Scholar Open Data Platform</em>,
		arXiv:2301.10140.
	</p>
	<p>
		The paper vectors are computed with SPECTER2 (Allen Institute for AI) from the paper's title
		and, where it exists, abstract. Only the resulting topic assignments are published, no vectors
		and no model. For the licence of the model, see its model card on Hugging Face.
	</p>

	{#if meta && !meta.fixture}
		<h2>When it was fetched</h2>
		<p>
			Release {meta.release} ({formatDate(meta.date)}) was built from data fetched on these dates:
		</p>
		<ul>
			{#each FETCHED as [key, label] (key)}
				{#if dates[key]}<li>{label}: {formatDate(dates[key])}</li>{/if}
			{/each}
		</ul>
		<p>
			Nothing is updated automatically; a new release means a new fetch. Changes at the sources
			since then are not reflected.
		</p>
	{/if}

	<h2>What the atlas stores and shows</h2>
	<ul>
		<li>
			<strong>Shown and published:</strong> titles, authors, years, venues, links to the DOI, DBLP and
			OpenAlex, which papers cite which (inside the atlas), and the atlas's own derived data (topic assignments
			with confidence, links between topics, map positions).
		</li>
		<li>
			<strong>Used but not shown, not published:</strong> abstracts and Semantic Scholar summaries. They
			help the tagger decide on a paper's topics and are kept on one computer.
		</li>
		<li>
			<strong>Never stored:</strong> full texts, and anything about the people who visit the site. The
			site sets no cookies and loads no outside scripts.
		</li>
	</ul>

	<h2>The licence of the atlas's own data and code</h2>
	<p>
		The code is under the MIT licence. The atlas's data releases are meant to be published under
		<strong>CC BY 4.0</strong>, which keeps the attribution the sources above ask for. The first
		dataset release is not published yet, so this is the stated plan, not an existing file; see
		<a href={resolve('/cite')}>Cite</a> for the current status. This is a careful reading of the licences,
		not legal advice.
	</p>
	<p>
		Found a wrong or missing source line? Use the <em>Suggest a change</em> links on any page, or
		the
		<a href={resolve('/about')}>About</a> page's pointers.
	</p>
</article>
