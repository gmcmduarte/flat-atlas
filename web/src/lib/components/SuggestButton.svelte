<script lang="ts">
	import ExternalLink from '#lib/components/ExternalLink.svelte';
	import { page } from '$app/state';
	import { SITE_BASE } from '#lib/site.js';
	import { OPTIONS, suggestUrl, type SuggestEntity } from '#lib/suggest.js';

	/**
	 * "Suggest a change" at the end of a topic, paper, author or venue page (PLAN §15.6). Plain
	 * links to pre-filled GitHub issue forms; the first one is the form for the usual problem.
	 * The pre-filled values are public (see `lib/suggest.ts`).
	 */
	let { entity, currentValue = '' }: { entity: SuggestEntity; currentValue?: string } = $props();

	const headingId = $props.id();
	const options = $derived(
		OPTIONS[entity.type].map((o) => ({
			...o,
			href: suggestUrl({
				template: o.template,
				entity,
				currentValue,
				pathname: page.url.pathname,
				base: SITE_BASE
			})
		}))
	);
</script>

<section class="suggest" aria-labelledby={headingId}>
	<h2 id={headingId}>Suggest a change</h2>
	<p class="muted">
		Tags and links here are made automatically and can be wrong. If you see a mistake, tell us: each
		link opens a GitHub form with this page's details already filled in. It needs a free GitHub
		account, and what you write is public.
	</p>
	<ul>
		{#each options as o, i (o.template)}
			<li>
				<ExternalLink
					href={o.href}
					class={i === 0 ? 'button' : undefined}
					data-suggest={i === 0 ? 'primary' : 'secondary'}
					data-template={o.template}>{o.label}</ExternalLink
				>
			</li>
		{/each}
	</ul>
</section>

<style>
	.suggest {
		margin-top: 2.5rem;
		padding-top: 0.5rem;
		border-top: 1px solid var(--line);
	}

	ul {
		list-style: none;
		padding: 0;
		margin: 0.6rem 0 0;
		display: grid;
		gap: 0.5rem;
		justify-items: start;
	}

	.suggest :global(a.button) {
		display: inline-block;
		padding: 0.4rem 0.9rem;
		border: 1px solid var(--accent);
		border-radius: 0.4rem;
		text-decoration: none;
		font-weight: 600;
	}

	.suggest :global(a.button:hover) {
		background: var(--chip);
	}
</style>
