<script lang="ts">
	import type { LateralEdgeType } from '#lib/data/index.js';
	import { EDGE_STYLES } from './style';

	/** What the edges on the map mean: one entry, for the one type being shown. */
	let { type, count }: { type: LateralEdgeType | 'none'; count: number } = $props();

	const style = $derived(type === 'none' ? null : EDGE_STYLES[type]);
</script>

<div class="legend" aria-live="polite">
	{#if style && type !== 'none'}
		<p class="head">
			<svg width="44" height="14" viewBox="0 0 44 14" aria-hidden="true" class={type}>
				<line x1="2" y1="7" x2={style.program === 'arrow' ? 34 : 42} y2="7" stroke-width="3" />
				{#if style.program === 'arrow'}
					<polygon points="44,7 33,2 33,12" />
				{/if}
			</svg>
			<strong>{style.label}:</strong>
			{style.meaning}
			<span class="muted">({style.drawn}.)</span>
		</p>
		<ul>
			<li>{style.weight}</li>
			<li>{style.confidence}</li>
			<li>
				The three edge types are never drawn together, and their confidences are not comparable with
				each other.
			</li>
		</ul>
		{#if count === 0}
			<p class="empty">
				No {style.label.toLowerCase()} links among the bubbles shown. Zoom in or expand a topic to see
				links between its subtopics.
			</p>
		{:else}
			<p class="muted">
				{count}
				{count === 1 ? 'link' : 'links'} drawn (the strongest few per bubble).
			</p>
		{/if}
		<p class="muted">Thin grey lines join a subtopic to its other parent topic.</p>
	{:else}
		<p class="muted">No edges drawn. Pick an edge type to see how topics are linked.</p>
	{/if}
</div>

<style>
	.legend {
		font-size: 0.9rem;
	}

	p {
		margin: 0.2rem 0;
	}

	ul {
		margin: 0.2rem 0;
		padding-left: 1.2rem;
	}

	.head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
	}

	svg line {
		stroke: currentColor;
	}

	svg polygon {
		fill: currentColor;
	}

	svg.related {
		color: #0f766e;
	}

	svg.builds-on {
		color: #c2410c;
	}

	svg.shared-community {
		color: #6d28d9;
	}

	@media (prefers-color-scheme: dark) {
		svg.related {
			color: #5eead4;
		}

		svg.builds-on {
			color: #fdba74;
		}

		svg.shared-community {
			color: #c4b5fd;
		}
	}

	.empty {
		padding: 0.4rem 0.6rem;
		border-left: 3px solid var(--muted);
		background: var(--chip);
	}
</style>
