<script lang="ts">
	import { resolve } from '$app/paths';
	import ConfidenceBadge from './ConfidenceBadge.svelte';
	import { SORT_LABELS, sortPapers, type SortKey } from '#lib/sortPapers.js';

	/** What a row needs; the topic list adds a confidence and the weak-match flag. */
	interface Row {
		work_id: string;
		title: string;
		year: number;
		venue_acronym: string;
		authors: string[];
		n_authors: number;
		cited_by_count: number;
		confidence?: number;
		low_confidence?: boolean;
	}

	let {
		papers,
		initialSort,
		emptyText = 'No papers.',
		label = 'Papers'
	}: { papers: Row[]; initialSort?: SortKey; emptyText?: string; label?: string } = $props();

	/** A list of one or two papers needs no sort switch. */
	const MIN_TO_SORT = 3;

	const hasConfidence = $derived(papers.some((p) => p.confidence !== undefined));
	const keys = $derived<SortKey[]>(
		hasConfidence ? ['relevance', 'cited', 'newest', 'oldest'] : ['cited', 'newest', 'oldest']
	);
	let chosen = $state<SortKey | undefined>(undefined);
	const sort = $derived<SortKey>(
		chosen && keys.includes(chosen)
			? chosen
			: initialSort && keys.includes(initialSort)
				? initialSort
				: keys[0]
	);

	const sorted = $derived(
		sortPapers(
			papers.map((p) => ({
				...p,
				confidence: p.confidence ?? 1,
				low_confidence: p.low_confidence ?? false
			})),
			sort
		)
	);
	const normal = $derived(sorted.filter((p) => !p.low_confidence));
	const weak = $derived(sorted.filter((p) => p.low_confidence));
	const selectId = $props.id();

	function who(p: Row): string {
		const names = p.authors.join(', ');
		return p.n_authors > p.authors.length ? `${names} et al.` : names;
	}
</script>

{#snippet item(p: (typeof sorted)[number])}
	<li>
		<a class="title" href={resolve('/paper/[id]', { id: p.work_id })}>{p.title}</a>
		{#if p.authors.length > 0}<span class="who">{who(p)}</span>{/if}
		<span class="muted">
			{p.venue_acronym}
			{p.year} · {p.cited_by_count} citation{p.cited_by_count === 1 ? '' : 's'}
		</span>
		{#if p.confidence !== undefined && hasConfidence}
			<ConfidenceBadge
				value={p.confidence}
				weak={p.low_confidence}
				title={p.low_confidence
					? 'Weak match: the best guess of the tagger for this paper'
					: 'Confidence of the topic tag'}
			/>
		{/if}
	</li>
{/snippet}

{#if papers.length === 0}
	<p class="muted">{emptyText}</p>
{:else}
	{#if papers.length >= MIN_TO_SORT}
		<div class="sort">
			<label for={selectId}>Sort by</label>
			<select
				id={selectId}
				value={sort}
				onchange={(e) => (chosen = e.currentTarget.value as SortKey)}
			>
				{#each keys as key (key)}
					<option value={key}>{SORT_LABELS[key]}</option>
				{/each}
			</select>
		</div>
	{/if}
	{#if normal.length > 0}
		<ul class="papers" aria-label={label}>
			{#each normal as p (p.work_id)}{@render item(p)}{/each}
		</ul>
	{/if}
	{#if weak.length > 0}
		<h3>Weak matches ({weak.length})</h3>
		<p class="muted">
			The tagger could not place these papers with confidence; the topic is its best guess.
		</p>
		<ul class="papers weak" aria-label="{label}, weak matches">
			{#each weak as p (p.work_id)}{@render item(p)}{/each}
		</ul>
	{/if}
{/if}

<style>
	.sort {
		margin: 0.5rem 0;
		display: flex;
		gap: 0.5rem;
		align-items: center;
	}

	select {
		padding: 0.25rem 0.4rem;
		border: 1px solid var(--line);
		border-radius: 0.3rem;
		background: var(--chip);
		color: inherit;
	}

	.papers {
		padding: 0;
		list-style: none;
		display: grid;
		gap: 0.7rem;
	}

	.papers li {
		display: flex;
		flex-wrap: wrap;
		gap: 0 0.6rem;
		align-items: baseline;
	}

	.title {
		font-weight: 600;
		flex-basis: 100%;
	}

	.who {
		font-size: 0.9rem;
	}

	h3 {
		margin: 1.4rem 0 0.2rem;
		font-size: 1rem;
	}
</style>
