<script lang="ts">
	import { band, explainProvenance, isWeakMatch } from '#lib/provenance.js';
	import type { Provenance } from '#lib/data/index.js';

	/**
	 * A confidence (0 to 1) as a percentage. With `provenance` (a tag of a work) the tooltip is
	 * the plain-language explanation and a weak match is labelled as such; with only `title` it
	 * is a plain badge, for edges. `showExplanation` also prints the sentence under the badge, so
	 * it is readable without a mouse.
	 */
	let {
		value,
		provenance,
		title = '',
		weak: weakFlag,
		showExplanation = false
	}: {
		value: number;
		provenance?: Provenance;
		title?: string;
		/** A weak match without a provenance at hand (a row of a topic's paper list). */
		weak?: boolean;
		showExplanation?: boolean;
	} = $props();

	const weak = $derived(weakFlag ?? isWeakMatch(provenance));
	const explanation = $derived(provenance ? explainProvenance(provenance, value) : title);
	const label = $derived(weak ? 'weak match' : provenance ? band(value) : '');
	const bandClass = $derived(weak ? 'weak' : provenance ? band(value) : '');
</script>

<span class="wrap">
	<span class="badge {bandClass}" title={explanation}>
		{Math.round(value * 100)}%{#if label}&nbsp;<span class="label">{label}</span>{/if}
	</span>
	{#if showExplanation && explanation}
		<span class="explain">{explanation}</span>
	{/if}
</span>

<style>
	.wrap {
		display: inline-flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 0.15rem;
	}

	.badge {
		display: inline-block;
		padding: 0 0.4rem;
		border-radius: 0.3rem;
		background: var(--chip);
		font-size: 0.8rem;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}

	.weak {
		border: 1px dashed var(--muted);
	}

	.low {
		border: 1px solid var(--muted);
	}

	.label {
		color: var(--muted);
	}

	.explain {
		font-size: 0.8rem;
		color: var(--muted);
		max-width: 40rem;
	}
</style>
