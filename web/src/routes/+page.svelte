<script lang="ts">
	import TopicList from '#lib/components/TopicList.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const topLevel = $derived(data.topics.filter((t) => t.level === 0));
</script>

<svelte:head>
	<title>The FLAT Atlas: topics in formal languages and automata theory</title>
	<meta
		name="description"
		content="An open map of formal languages and automata theory: topics, papers, authors and venues, with the confidence and provenance of every topic assignment."
	/>
</svelte:head>

<h1>The FLAT Atlas</h1>
<p class="muted">
	A map of formal languages and automata theory: topics, papers, authors and venues. Start from a
	top-level topic below or use the search box.
</p>

<h2>Top-level topics</h2>
<TopicList topics={topLevel} allTopics={data.topics} />
