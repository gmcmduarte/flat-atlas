<script lang="ts">
	import type { HTMLAnchorAttributes } from 'svelte/elements';

	/**
	 * A link to another site (GitHub, a source). Internal links use `resolve()`; this component
	 * is the one place that says "this is external", so the lint rule stays on everywhere else.
	 */
	let { href, children, ...rest }: HTMLAnchorAttributes & { href: string } = $props();
</script>

<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -->
<a {href} rel="noopener noreferrer" {...rest}>{@render children?.()}</a>
