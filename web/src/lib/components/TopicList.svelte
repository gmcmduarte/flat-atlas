<script lang="ts">
	import { resolve } from '$app/paths';
	import type { Topic } from '#lib/data/index.js';

	/**
	 * `topics` are the ones listed; `allTopics` (default: the same) is where subtopic names are
	 * looked up, for a list that shows only the top level.
	 */
	let { topics, allTopics }: { topics: Topic[]; allTopics?: Topic[] } = $props();

	const nameOf = $derived(new Map((allTopics ?? topics).map((t) => [t.topic_id, t.name])));
</script>

{#if topics.length === 0}
	<p class="muted">No topics yet.</p>
{:else}
	<ul class="topic-list">
		{#each topics as topic (topic.topic_id)}
			<li>
				<a class="name" href={resolve('/topic/[id]', { id: topic.topic_id })}>{topic.name}</a>
				<span class="muted">{topic.paper_count} papers</span>
				<p>{topic.description}</p>
				{#if topic.children.length > 0}
					<ul class="chips" aria-label="Subtopics of {topic.name}">
						{#each topic.children as childId (childId)}
							<li>
								<a href={resolve('/topic/[id]', { id: childId })}
									>{nameOf.get(childId) ?? childId}</a
								>
							</li>
						{/each}
					</ul>
				{/if}
			</li>
		{/each}
	</ul>
{/if}

<style>
	.topic-list {
		padding: 0;
		list-style: none;
		display: grid;
		gap: 1.25rem;
	}

	.name {
		font-size: 1.15rem;
		font-weight: 600;
	}

	p {
		margin: 0.2rem 0;
	}
</style>
