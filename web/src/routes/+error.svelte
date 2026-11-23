<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';

	const notFound = $derived(page.status === 404);
</script>

<svelte:head>
	<title>{notFound ? 'Not found' : 'Something went wrong'} · The FLAT Atlas</title>
	<meta name="robots" content="noindex" />
</svelte:head>

<h1>{notFound ? 'Not found' : 'Something went wrong'}</h1>
{#if notFound}
	<p>{page.error?.message ?? 'There is nothing at this address.'}</p>
	<p>Try the search box above, or <a href={resolve('/')}>start from the top-level topics</a>.</p>
{:else}
	<p>The page could not be loaded. {page.error?.message ?? ''}</p>
	<p class="muted">
		This usually means the data files could not be fetched. Reload the page, or
		<a href={resolve('/')}>go back to the topics</a>.
	</p>
{/if}
