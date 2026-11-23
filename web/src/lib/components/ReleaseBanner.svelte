<script lang="ts">
	import ExternalLink from '#lib/components/ExternalLink.svelte';
	import { resolve } from '$app/paths';
	import type { DataInfo } from '#lib/data/types.js';
	import { REPO_URL } from '#lib/site.js';
	import { coverageSentence, formatDate } from '#lib/venues.js';

	/**
	 * The notice at the top of every page: what this data is and that it is a pilot. Everything
	 * in it is read from `meta.json` (release, date, counts, venues).
	 */
	let { meta }: { meta: DataInfo | null | undefined } = $props();
</script>

<aside class="banner" aria-label="About this data">
	<div class="inner">
		{#if meta?.fixture}
			<p>
				<strong>Fixture data.</strong> Everything shown here is invented for development; it is not the
				real corpus.
			</p>
		{:else if meta}
			<p>
				<strong>Pilot.</strong>
				{coverageSentence(meta)}; release {meta.release}, {formatDate(meta.date)}. Topic assignments
				are automatic and can be wrong.
				<a href={resolve('/methods')}>How they are made</a>
				·
				<ExternalLink href="{REPO_URL}/issues/new/choose">Suggest a correction</ExternalLink>
			</p>
		{:else}
			<p><strong>Pilot.</strong> Early development.</p>
		{/if}
	</div>
</aside>

<style>
	.banner {
		background: var(--banner-bg);
		color: var(--banner-fg);
		border-bottom: 1px solid var(--banner-line);
		font-size: 0.9rem;
	}

	.inner {
		box-sizing: border-box;
		max-width: 62rem;
		margin: 0 auto;
		padding: 0.5rem 1rem;
	}

	p {
		margin: 0;
	}

	.banner :global(a) {
		color: inherit;
		font-weight: 600;
	}
</style>
