<script lang="ts">
	import ExternalLink from '#lib/components/ExternalLink.svelte';
	import ReleaseBanner from '#lib/components/ReleaseBanner.svelte';
	import SearchBox from '#lib/components/SearchBox.svelte';
	import { focusMapOn } from '#lib/map/focusHandler.js';
	import { REPO_URL, SITE_BASE, SITE_URL } from '#lib/site.js';
	import { navigating, page } from '$app/state';
	import { asset, resolve } from '$app/paths';
	import type { LayoutProps } from './$types';
	import './layout.css';

	let { data, children }: LayoutProps = $props();

	const meta = $derived(data.meta);

	const SHARE_TITLE = 'The FLAT Atlas';
	const SHARE_TEXT =
		'An open map of formal languages and automata theory: topics, papers, authors and venues.';
	// The public address of this page (not the address the build or a local server runs on).
	const canonical = $derived.by(() => {
		let path = page.url.pathname;
		if (path.startsWith(SITE_BASE)) path = path.slice(SITE_BASE.length);
		return `${SITE_URL}${path || '/'}`;
	});
	const image = `${SITE_URL}/og.png`;
</script>

<svelte:head>
	<link rel="icon" href={asset('favicon.svg')} type="image/svg+xml" />
	<link rel="apple-touch-icon" href={asset('apple-touch-icon.png')} />
	<meta name="theme-color" content="#12161d" />
	<link rel="canonical" href={canonical} />
	<meta property="og:site_name" content={SHARE_TITLE} />
	<meta property="og:type" content="website" />
	<meta property="og:url" content={canonical} />
	<meta property="og:image" content={image} />
	<meta property="og:image:width" content="1200" />
	<meta property="og:image:height" content="630" />
	<meta property="og:image:alt" content="Bubbles inside bubbles: the shape of the topic map." />
	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:image" content={image} />
	<meta name="twitter:title" content={SHARE_TITLE} />
	<meta name="twitter:description" content={SHARE_TEXT} />
	<meta property="og:title" content={SHARE_TITLE} />
	<meta property="og:description" content={SHARE_TEXT} />
</svelte:head>

<a class="skip" href="#main">Skip to the content</a>

{#if navigating.to}
	<div class="loading" role="status">
		<span class="bar"></span>
		<span class="sr-only">Loading…</span>
	</div>
{/if}

<div class="page">
	<ReleaseBanner {meta} />
	<header>
		<a class="brand" href={resolve('/')}>The FLAT Atlas</a>
		<nav aria-label="Main">
			<a href={resolve('/')}>Topics</a>
			<a href={resolve('/methods')}>Methods</a>
			<a href={resolve('/sources')}>Sources</a>
			<a href={resolve('/cite')}>Cite</a>
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
			<a href="https://www.semanticscholar.org">Semantic Scholar</a> (ODC-BY). Links and metadata
			only; no full texts. <a href={resolve('/sources')}>All sources and licences</a>.
		</p>
		<p>
			<a href={resolve('/methods')}>Methods</a> ·
			<a href={resolve('/cite')}>How to cite</a> ·
			<a href={resolve('/about')}>About</a> ·
			<ExternalLink href={REPO_URL}>Source on GitHub</ExternalLink> ·
			<ExternalLink href="{REPO_URL}/issues/new/choose">Suggest a correction</ExternalLink>
		</p>
		<p>
			{#if meta?.fixture}
				Early development: everything shown here is fixture data, not the real corpus.
			{:else if meta}
				Release {meta.release} ({meta.date}), {meta.works.toLocaleString('en')} works, tagged with
				{meta.tagger_version}. Topic assignments are automatic and carry a confidence. Code: MIT.
				Data: CC BY 4.0.
			{:else}
				Early development.
			{/if}
		</p>
	</footer>
</div>
