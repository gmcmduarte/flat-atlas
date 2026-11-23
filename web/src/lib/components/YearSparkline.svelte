<script lang="ts">
	/**
	 * Bars per year from the first to the last year in `points`, years without a point shown as
	 * zero. The summary text gives the same numbers to a screen reader.
	 */
	let { points, unit = 'papers' }: { points: { year: number; value: number }[]; unit?: string } =
		$props();

	const BAR = 8;
	const GAP = 2;
	const HEIGHT = 40;

	const bars = $derived.by(() => {
		if (points.length === 0) return [];
		const byYear = new Map(points.map((p) => [p.year, p.value]));
		const first = Math.min(...byYear.keys());
		const last = Math.max(...byYear.keys());
		return Array.from({ length: last - first + 1 }, (_, i) => ({
			year: first + i,
			value: byYear.get(first + i) ?? 0
		}));
	});
	const max = $derived(Math.max(1, ...bars.map((b) => b.value)));
	const total = $derived(bars.reduce((sum, b) => sum + b.value, 0));
	const peak = $derived(bars.reduce((best, b) => (b.value > best.value ? b : best), bars[0]));
</script>

{#if bars.length === 0}
	<p class="muted">No {unit} to show yet.</p>
{:else}
	<figure>
		<svg
			viewBox="0 0 {bars.length * (BAR + GAP)} {HEIGHT}"
			preserveAspectRatio="none"
			role="img"
			aria-label="{total} {unit} from {bars[0].year} to {bars[bars.length - 1]
				.year}; the most in {peak.year} ({peak.value})"
		>
			{#each bars as b, i (b.year)}
				<rect
					x={i * (BAR + GAP)}
					y={HEIGHT - (b.value / max) * (HEIGHT - 2)}
					width={BAR}
					height={(b.value / max) * (HEIGHT - 2)}
				>
					<title>{b.year}: {b.value}</title>
				</rect>
			{/each}
		</svg>
		<figcaption class="muted">
			{bars[0].year} to {bars[bars.length - 1].year} · most in {peak.year} ({peak.value})
		</figcaption>
	</figure>
{/if}

<style>
	figure {
		margin: 0.5rem 0;
	}

	svg {
		width: 100%;
		max-width: 32rem;
		height: 3.5rem;
		fill: var(--accent);
	}

	figcaption {
		font-size: 0.85rem;
	}
</style>
