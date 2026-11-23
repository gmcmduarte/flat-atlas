<script lang="ts">
	import { resolve } from '$app/paths';

	let { topics, label }: { topics: { topic_id: string; name: string }[]; label: string } = $props();
</script>

{#if topics.length > 0}
	<ul class="chips" aria-label={label}>
		{#each topics as topic (topic.topic_id)}
			<li><a href={resolve('/topic/[id]', { id: topic.topic_id })}>{topic.name}</a></li>
		{/each}
	</ul>
{/if}

<style>
	li a {
		display: inline-block;
		padding: 0.1rem 0.6rem;
		border-radius: 1rem;
		background: var(--chip);
		text-decoration: none;
	}

	li a:hover {
		text-decoration: underline;
	}
</style>
