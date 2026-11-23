<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { goto, replaceState } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import {
		browserDataSource,
		type LateralEdgeType,
		type MapLayout,
		type Topic
	} from '#lib/data/index.js';
	import EdgeLegend from './EdgeLegend.svelte';
	import { aggregateEdges, EDGE_TYPES, ghostLinks } from './edges';
	import { registerMapFocus } from './focusHandler';
	import { buildIndex, ancestorsOf } from './model';
	import { PageLoader } from './pageLoader';
	import { EDGE_STYLES } from './style';
	import TopicMap, { type HoverInfo } from './TopicMap.svelte';
	import TopicTree from './TopicTree.svelte';
	import { treeRows, type TreeAction } from './treeNav';
	import { readFocus, withFocus } from './urlState';
	import {
		EMPTY_STATE,
		collapseTopic,
		cutOf,
		expandTopic,
		focusOf,
		goBack,
		stateForFocus,
		zoomChanges,
		type MapState,
		type OnScreen,
		type Viewport
	} from './visible';

	/**
	 * The map section of the home page: the canvas, its toolbar and legend, the list view, and
	 * the state that ties them together (which topics are open, which is selected, which has the
	 * keyboard focus) and the URL.
	 */
	let { topics }: { topics: Topic[] } = $props();

	let layout = $state.raw<MapLayout | null>(null);
	let loader = $state.raw<PageLoader | undefined>();
	let failed = $state(false);
	let mapState = $state.raw<MapState>(EMPTY_STATE);
	let view = $state<'map' | 'list'>('map');
	let edgeType = $state<LateralEdgeType | 'none'>('related');
	let focusedId = $state<string | null>(null);
	let hover = $state.raw<HoverInfo | null>(null);
	let pagesVersion = $state(0);
	let announcement = $state('');
	let mounted = $state(false);
	let startAt = $state<string | null>(null);
	let onScreenIds: string[] = [];
	let canvas = $state<ReturnType<typeof TopicMap> | undefined>();

	const index = $derived(layout ? buildIndex(layout, topics) : null);
	const cut = $derived(index ? cutOf(index, mapState.expanded) : null);
	const rows = $derived(index ? treeRows(index, mapState.expanded) : []);
	const ghosts = $derived(index && cut ? ghostLinks(index, cut) : []);
	const edges = $derived.by(() => {
		void pagesVersion;
		if (!index || !cut || !loader || edgeType === 'none') return [];
		return aggregateEdges(index, cut, loader.loaded, edgeType);
	});
	const shownTopic = $derived(
		index && (mapState.selected ?? focusedId)
			? (index.topics.get((mapState.selected ?? focusedId)!) ?? null)
			: null
	);
	const trail = $derived(
		index && shownTopic
			? [...ancestorsOf(index, shownTopic.id)]
					.reverse()
					.map((id) => index.topics.get(id)?.name ?? id)
			: []
	);
	const hoverTopic = $derived(index && hover ? (index.topics.get(hover.id) ?? null) : null);
	const hoverAuthors = $derived.by(() => {
		void pagesVersion;
		const page = hover ? loader?.loaded.get(hover.id) : undefined;
		return page ? page.key_authors.slice(0, 3).map((a) => a.name) : null;
	});
	const canGoBack = $derived(mapState.expanded.length > 0 || mapState.selected !== null);

	// ---- data --------------------------------------------------------------------------------

	onMount(() => {
		const source = browserDataSource();
		const stop = registerMapFocus(focusTopic);
		let dead = false;
		source
			.getMap()
			.then((data) => {
				if (dead) return;
				layout = data;
				loader = new PageLoader(source);
				const built = buildIndex(data, topics);
				const focus = readFocus(page.url.search, built);
				if (focus) {
					mapState = stateForFocus(built, focus);
					focusedId = focus;
					startAt = focus;
				}
				mounted = true;
			})
			.catch(() => {
				failed = true;
			});
		return () => {
			dead = true;
			stop();
		};
	});

	// The pages of the bubbles drawn: their edges and their key authors.
	$effect(() => {
		const l = loader;
		const c = cut;
		if (!l || !c) return;
		void l.load(c.bubbles).then(() => pagesVersion++);
	});

	// ---- URL ---------------------------------------------------------------------------------

	function writeUrl(attempt = 0) {
		const focus = index ? focusOf(index, mapState) : null;
		const next = withFocus(page.url, focus);
		if (next.search === page.url.search) return;
		try {
			// `next` is the current URL with only the query changed.
			// eslint-disable-next-line svelte/no-navigation-without-resolve
			replaceState(next, page.state);
		} catch {
			// the router is not ready on the very first tick of the page
			if (attempt < 5) setTimeout(() => writeUrl(attempt + 1), 60);
		}
	}

	$effect(() => {
		void mapState;
		if (mounted) untrack(writeUrl);
	});

	// A link to `/?focus=…` or a click on "Topics" while the map is open moves the map.
	$effect(() => {
		const raw = page.url.searchParams.get('focus');
		if (!mounted || !index) return;
		const wanted = raw && index.topics.has(raw) ? raw : null;
		untrack(() => {
			if (!index || wanted === focusOf(index, mapState)) return;
			mapState = stateForFocus(index, wanted);
			focusedId = wanted;
			if (view === 'map') {
				if (wanted) canvas?.zoomToTopic(wanted);
				else canvas?.fitAll();
			}
		});
	});

	// ---- actions -----------------------------------------------------------------------------

	function say(text: string) {
		announcement = text;
	}

	function describe(id: string): string {
		const t = index?.topics.get(id);
		return t ? `${t.name}, ${t.paperCount} papers` : id;
	}

	function expandAndZoom(id: string) {
		if (!index) return;
		const t = index.topics.get(id);
		if (!t) return;
		const result = expandTopic(index, mapState, id, { protect: onScreenIds });
		if (result.refused) {
			say('The map is full: close a topic with Back before opening another.');
			return;
		}
		mapState = result.state;
		focusedId = id;
		if (view === 'map') canvas?.zoomToTopic(id);
		say(
			t.children.length > 0
				? `Expanded ${t.name}: ${t.children.length} subtopics.`
				: `Selected ${describe(id)}.`
		);
	}

	function collapse(id: string) {
		if (!index) return;
		const t = index.topics.get(id);
		mapState = collapseTopic(index, mapState, id);
		focusedId = id;
		if (view === 'map') {
			if (t?.parentId) canvas?.zoomToTopic(t.parentId);
			else canvas?.fitAll();
		}
		say(`Collapsed ${t?.name ?? id}.`);
	}

	function back() {
		if (!index) return;
		const result = goBack(index, mapState);
		mapState = result.state;
		if (result.collapsed) {
			const t = index.topics.get(result.collapsed);
			focusedId = result.collapsed;
			if (view === 'map') {
				if (t?.parentId) canvas?.zoomToTopic(t.parentId);
				else canvas?.fitAll();
			}
			say(`Collapsed ${t?.name ?? result.collapsed}.`);
		} else if (view === 'map') {
			canvas?.fitAll();
		}
	}

	function reset() {
		mapState = EMPTY_STATE;
		focusedId = null;
		if (view === 'map') canvas?.fitAll();
		say('Showing all top-level topics.');
	}

	function open(id: string) {
		void goto(resolve('/topic/[id]', { id }));
	}

	/** The header search chose a topic: show it on the map instead of leaving the page. */
	function focusTopic(id: string): boolean {
		if (!index || !index.topics.has(id)) return false;
		const result = expandTopic(index, EMPTY_STATE, id);
		mapState = result.state;
		focusedId = id;
		if (view === 'map') canvas?.zoomToTopic(id);
		document.getElementById('topic-map')?.scrollIntoView({ block: 'nearest' });
		say(`Showing ${describe(id)} on the map.`);
		return true;
	}

	function onAction(action: TreeAction, id: string) {
		if (action === 'expand') expandAndZoom(id);
		else if (action === 'collapse') collapse(id);
		else if (action === 'toggle') {
			if (rows.find((r) => r.id === id)?.expanded) collapse(id);
			else expandAndZoom(id);
		} else if (action === 'select') {
			mapState = { ...mapState, selected: id };
			focusedId = id;
			if (view === 'map') canvas?.zoomToTopic(id);
		} else if (action === 'open') open(id);
		else if (action === 'back') back();
	}

	function onMove(id: string) {
		if (focusedId === id) return;
		focusedId = id;
		if (view === 'map') canvas?.ensureVisible(id);
	}

	function onScreen(list: OnScreen[], viewport: Viewport) {
		if (!index || !cut) return;
		onScreenIds = list.filter((s) => s.visible).map((s) => s.id);
		const changes = zoomChanges(index, cut, list, { viewport });
		let next = mapState;
		for (const id of changes.collapse) {
			const parent = index.topics.get(id)?.parentId ?? null;
			next = { ...collapseTopic(index, next, id), selected: parent };
		}
		for (const id of changes.expand) {
			const result = expandTopic(index, next, id, { protect: onScreenIds });
			if (!result.refused) next = result.state;
		}
		if (next !== mapState) mapState = next;
	}

	async function showView(next: 'map' | 'list') {
		view = next;
		if (next === 'map') {
			await new Promise((r) => requestAnimationFrame(r));
			const focus = index ? focusOf(index, mapState) : null;
			if (focus) canvas?.zoomToTopic(focus, false);
			else canvas?.fitAll(false);
		}
	}

	function onHover(info: HoverInfo | null) {
		hover = info;
		if (info && loader && !loader.loaded.has(info.id)) {
			void loader.load([info.id]).then(() => pagesVersion++);
		}
	}
</script>

<section id="topic-map" aria-labelledby="map-heading" class="map-section">
	<h2 id="map-heading">Map of topics</h2>

	{#if failed}
		<p class="notice">
			The map could not be loaded. The list of topics below has the same information.
		</p>
	{:else if !index || !cut}
		<p class="notice muted" role="status">Loading the map…</p>
		<noscript
			><p class="notice">The map needs JavaScript. The list of topics below does not.</p></noscript
		>
	{:else}
		<div class="toolbar">
			<div class="group" role="group" aria-label="Navigate">
				<button type="button" onclick={back} disabled={!canGoBack}>← Back</button>
				<button type="button" onclick={reset} disabled={!canGoBack}>All topics</button>
				{#if view === 'map'}
					<button type="button" onclick={() => canvas?.zoomBy(1.6)} aria-label="Zoom in">＋</button>
					<button type="button" onclick={() => canvas?.zoomBy(1 / 1.6)} aria-label="Zoom out"
						>－</button
					>
				{/if}
			</div>
			<div class="group" role="group" aria-label="View">
				<button type="button" aria-pressed={view === 'map'} onclick={() => showView('map')}
					>Map</button
				>
				<button type="button" aria-pressed={view === 'list'} onclick={() => showView('list')}
					>List</button
				>
			</div>
			<fieldset class="group edge-types">
				<legend>Links shown</legend>
				{#each EDGE_TYPES as type (type)}
					<label>
						<input type="radio" name="edge-type" value={type} bind:group={edgeType} />
						{EDGE_STYLES[type].label}
					</label>
				{/each}
				<label>
					<input type="radio" name="edge-type" value="none" bind:group={edgeType} />
					None
				</label>
			</fieldset>
		</div>

		<div class="stage" hidden={view !== 'map'}>
			<TopicMap
				bind:this={canvas}
				{index}
				bubbles={cut.bubbles}
				hulls={cut.hulls}
				{edges}
				{ghosts}
				{edgeType}
				selectedId={mapState.selected}
				{focusedId}
				{startAt}
				onbubble={expandAndZoom}
				onhull={collapse}
				onopen={open}
				onhover={onHover}
				onscreen={onScreen}
			/>
			{#if hover && hoverTopic}
				<div
					class="tooltip"
					aria-hidden="true"
					style:left="{hover.x}px"
					style:top="{Math.max(8, hover.y - hover.r - 10)}px"
				>
					<strong>{hoverTopic.name}</strong>
					<span>Volume {hoverTopic.volume.toFixed(1)} · {hoverTopic.paperCount} papers</span>
					{#if hoverAuthors && hoverAuthors.length > 0}
						<span>Top authors: {hoverAuthors.join(', ')}</span>
					{/if}
				</div>
			{/if}
		</div>

		{#if view === 'list'}
			<p class="muted hint">
				The same topics as the map, as a list. Open or close a topic with its row; the map keeps the
				same state.
			</p>
		{:else}
			<p class="muted hint">
				Bubble size is research volume. Click a bubble to open it, double-click to go to its page.
				Keyboard: Tab to the topic tree, then arrow keys; Right opens, Left closes, Enter opens the
				topic page.
			</p>
		{/if}

		<TopicTree
			{rows}
			current={focusedId}
			selected={mapState.selected}
			variant={view === 'list' ? 'list' : 'mirror'}
			onmove={onMove}
			onaction={onAction}
		/>

		<div class="panel">
			{#if shownTopic}
				<p class="selected">
					{#if trail.length > 0}<span class="muted">{trail.join(' › ')} › </span>{/if}
					<strong>{shownTopic.name}</strong>
					<span class="muted">{shownTopic.paperCount} papers</span>
					<a href={resolve('/topic/[id]', { id: shownTopic.id })}>Open topic page</a>
				</p>
			{/if}
			<EdgeLegend type={edgeType} count={edges.length} />
		</div>
		<p class="sr-only" role="status">{announcement}</p>
	{/if}
</section>

<style>
	.map-section {
		margin: 1.5rem 0 2rem;
	}

	.map-section h2 {
		margin-top: 0;
	}

	.toolbar {
		display: flex;
		flex-wrap: wrap;
		gap: 0.6rem 1.2rem;
		align-items: center;
		margin-bottom: 0.6rem;
	}

	.group {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		align-items: center;
		margin: 0;
		padding: 0;
		border: 0;
	}

	.edge-types legend {
		float: left;
		padding: 0 0.4rem 0 0;
		font-size: 0.9rem;
		color: var(--muted);
	}

	.edge-types label {
		display: inline-flex;
		gap: 0.25rem;
		align-items: center;
		font-size: 0.9rem;
	}

	button {
		padding: 0.3rem 0.7rem;
		border: 1px solid var(--muted);
		border-radius: 0.4rem;
		background: var(--chip);
		color: inherit;
		font: inherit;
		cursor: pointer;
	}

	button:disabled {
		opacity: 0.5;
		cursor: default;
	}

	button[aria-pressed='true'] {
		background: var(--accent);
		border-color: var(--accent);
		color: var(--bg);
	}

	.stage {
		position: relative;
		height: min(70vh, 40rem);
		border: 1px solid var(--line);
		border-radius: 0.5rem;
		background: var(--bg);
		overflow: hidden;
	}

	.stage[hidden] {
		display: none;
	}

	.tooltip {
		position: absolute;
		z-index: 5;
		display: grid;
		gap: 0.1rem;
		max-width: 18rem;
		transform: translate(-50%, -100%);
		padding: 0.4rem 0.6rem;
		border: 1px solid var(--line);
		border-radius: 0.4rem;
		background: var(--bg);
		box-shadow: 0 0.3rem 1rem rgb(0 0 0 / 0.2);
		font-size: 0.85rem;
		pointer-events: none;
	}

	.hint {
		margin: 0.4rem 0;
		font-size: 0.85rem;
	}

	.panel {
		margin-top: 0.6rem;
	}

	.selected {
		margin: 0.2rem 0 0.6rem;
		display: flex;
		flex-wrap: wrap;
		gap: 0.3rem 0.8rem;
		align-items: baseline;
	}

	.notice {
		padding: 0.6rem 0.8rem;
		border: 1px dashed var(--line);
		border-radius: 0.4rem;
	}

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip-path: inset(50%);
		white-space: nowrap;
	}
</style>
