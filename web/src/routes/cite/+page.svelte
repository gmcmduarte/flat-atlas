<script lang="ts">
	import ExternalLink from '#lib/components/ExternalLink.svelte';
	import { resolve } from '$app/paths';
	import { REPO_URL, SITE_URL } from '#lib/site.js';
	import { formatDate } from '#lib/venues.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const meta = $derived(data.meta);
	const real = $derived(meta && !meta.fixture ? meta : null);
	const year = $derived(real ? real.date.slice(0, 4) : '2026');
	const bibtex = $derived(
		`@misc{flatatlas${year},
  author       = {Duarte, Guilherme},
  title        = {The {FLAT} Atlas: an open map of formal languages and automata theory},
  year         = {${year}},
  howpublished = {\\url{${SITE_URL}/}},
  note         = {Pilot release ${real?.release ?? '(version)'}, ${real ? formatDate(real.date) : '(date)'}. DOI: not yet assigned}
}`
	);
</script>

<svelte:head>
	<title>Cite · The FLAT Atlas</title>
	<meta
		name="description"
		content="How to cite the FLAT Atlas and its data, and which sources to cite with it."
	/>
</svelte:head>

<article class="prose">
	<h1>Cite</h1>
	<p class="lead">
		If the atlas helps your work, please cite it, and say which release you used: tags and links
		change from release to release.
	</p>

	<h2>This release</h2>
	{#if real}
		<p>
			You are looking at release <strong>{real.release}</strong> ({formatDate(real.date)}), tagged
			with {real.tagger_version}, topic list version {real.taxonomy_version}.
		</p>
	{:else}
		<p class="note">
			This copy of the site shows invented fixture data. Cite only the real site and its releases.
		</p>
	{/if}

	<h3>As text</h3>
	<p>
		Duarte, G. ({year}).
		<em>The FLAT Atlas: an open map of formal languages and automata theory</em>
		{#if real}(pilot release {real.release}, {formatDate(real.date)}){/if}. {SITE_URL}/
	</p>

	<h3>As BibTeX</h3>
	<pre><code>{bibtex}</code></pre>

	<h2>A permanent identifier (DOI)</h2>
	<p class="note">
		<strong>DOI: not yet assigned.</strong> The data will be archived on Zenodo, which gives each release
		a DOI. Until then, cite the address and the release name above. This page will show the DOI when it
		exists.
	</p>

	<h2>Citing the sources too</h2>
	<p>
		The atlas rests on DBLP, OpenAlex, Crossref and Semantic Scholar. If you use data from the
		atlas, please credit them as well; <a href={resolve('/sources')}>Sources</a> lists what each one contributes
		and how Semantic Scholar asks to be cited.
	</p>

	<h2>For software tools</h2>
	<p>
		The repository has a <code>CITATION.cff</code> file, which GitHub and reference managers read:
		<ExternalLink href={REPO_URL}>{REPO_URL.replace('https://', '')}</ExternalLink>.
	</p>
</article>
