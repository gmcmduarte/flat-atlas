<script lang="ts">
	import TopicList from '#lib/components/TopicList.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const topLevel = $derived(data.topics.filter((t) => t.level === 0));
</script>

<svelte:head>
	<title>Topics · The FLAT Atlas</title>
</svelte:head>

<h1>The FLAT Atlas</h1>
<p class="muted">
	A map of formal languages and automata theory: topics, papers, authors and venues. This is an
	early skeleton showing fixture data.
</p>

<h2>Top-level topics</h2>
<TopicList topics={topLevel} allTopics={data.topics} />
