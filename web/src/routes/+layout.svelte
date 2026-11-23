<script lang="ts">
	import favicon from '#lib/assets/favicon.svg';
	import SearchBox from '#lib/components/SearchBox.svelte';
	import { focusMapOn } from '#lib/map/focusHandler.js';
	import { navigating } from '$app/state';
	import { resolve } from '$app/paths';
	import type { LayoutProps } from './$types';
	import './layout.css';

	let { data, children }: LayoutProps = $props();

	const meta = $derived(data.meta);
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<a class="skip" href="#main">Skip to the content</a>

{#if navigating.to}
	<div class="loading" role="status">
		<span class="bar"></span>
		<span class="sr-only">Loading…</span>
	</div>
{/if}

<div class="page">
	<header>
		<a class="brand" href={resolve('/')}>The FLAT Atlas</a>
		<nav aria-label="Main">
			<a href={resolve('/')}>Topics</a>
			<a href={resolve('/about')}>About</a>
		</nav>
		<SearchBox onTopic={focusMapOn} />
	</header>

	<main id="main" tabindex="-1">
		{@render children()}
	</main>

	<footer>
		<p>
			Metadata from <a href="https://dblp.org">DBLP</a> (CC0),
			<a href="https://openalex.org">OpenAlex</a> (CC0),
			<a href="https://www.crossref.org">Crossref</a> and
			<a href="https://www.semanticscholar.org">Semantic Scholar</a>. Links and metadata only; no
			full texts.
		</p>
		<p>
			<a href="https://github.com/gmcmduarte/flat-atlas">Source on GitHub</a> ·
			{#if meta?.fixture}
				Early development: everything shown here is fixture data, not the real corpus.
			{:else if meta}
				Data: release {meta.release} ({meta.date}), {meta.works.toLocaleString('en')} works, tagged with
				{meta.tagger_version}. Topic assignments are automatic and carry a confidence.
			{:else}
				Early development.
			{/if}
		</p>
	</footer>
</div>
