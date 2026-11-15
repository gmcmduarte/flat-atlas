<script lang="ts">
	/** A tag's confidence (0 to 1) as a percentage; the title tells where it comes from. */
	let { value, title = '' }: { value: number; title?: string } = $props();
</script>

<span class="badge" {title}>{Math.round(value * 100)}%</span>

<style>
	.badge {
		display: inline-block;
		padding: 0 0.4rem;
		border-radius: 0.3rem;
		background: var(--chip);
		font-size: 0.8rem;
		font-variant-numeric: tabular-nums;
	}
</style>
