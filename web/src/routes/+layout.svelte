<script lang="ts">
	import favicon from '#lib/assets/favicon.svg';
	import { resolve } from '$app/paths';
	import type { LayoutProps } from './$types';
	import './layout.css';

	let { children }: LayoutProps = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>The FLAT Atlas</title>
</svelte:head>

<div class="page">
	<header>
		<a class="brand" href={resolve('/')}>The FLAT Atlas</a>
		<nav aria-label="Main">
			<a href={resolve('/')}>Topics</a>
			<a href={resolve('/about')}>About</a>
		</nav>
		<form role="search" onsubmit={(e) => e.preventDefault()}>
			<input
				type="search"
				placeholder="Search (coming soon)"
				aria-label="Search (not available yet)"
				disabled
			/>
		</form>
	</header>

	<main>
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
			<a href="https://github.com/gmcmduarte/flat-atlas">Source on GitHub</a> · Early development: everything
			shown here is fixture data.
		</p>
	</footer>
</div>
