<script lang="ts">
	/**
	 * The canvas of the topic map: Sigma.js (WebGL) with graphology. This is the only file that
	 * imports either (CLAUDE.md, P1-11); everything it decides on (which topics are drawn, which
	 * edges, what a click does) comes in as props, and everything the user does goes out as
	 * callbacks. Positions and radii are the precomputed ones from `map.json`: nothing is laid
	 * out in the browser.
	 */
	import { onMount, untrack } from 'svelte';
	import type Graph from 'graphology';
	import type Sigma from 'sigma';
	import type { NodeHoverDrawingFunction, NodeLabelDrawingFunction } from 'sigma/rendering';
	import type { LateralEdgeType } from '#lib/data/index.js';
	import type { GhostLink, MapEdge } from './edges';
	import { normaliseWeights } from './edges';
	import type { MapIndex } from './model';
	import { bubbleColour, edgeAppearance, ghostColour, hullColour, type Scheme } from './style';
	import type { OnScreen, Viewport } from './visible';

	export interface HoverInfo {
		id: string;
		/** Centre of the bubble in pixels from the top left of the map. */
		x: number;
		y: number;
		/** Radius in pixels. */
		r: number;
	}

	let {
		index,
		bubbles,
		hulls,
		edges,
		ghosts,
		edgeType,
		selectedId = null,
		focusedId = null,
		onbubble,
		onhull,
		onopen,
		onhover,
		onscreen,
		onstatus,
		startAt = null
	}: {
		index: MapIndex;
		bubbles: string[];
		hulls: string[];
		edges: MapEdge[];
		ghosts: GhostLink[];
		edgeType: LateralEdgeType | 'none';
		selectedId?: string | null;
		focusedId?: string | null;
		onbubble: (id: string) => void;
		onhull: (id: string) => void;
		onopen: (id: string) => void;
		onhover: (info: HoverInfo | null) => void;
		onscreen: (list: OnScreen[], viewport: Viewport) => void;
		onstatus?: (status: 'loading' | 'ready' | 'error') => void;
		/** The topic to show on first paint (from the URL); all level-0 bubbles when null. */
		startAt?: string | null;
	} = $props();

	/** The bounding box given to Sigma: normalised coordinates are (v + EXTENT) / (2 × EXTENT). */
	const EXTENT = 600;
	const FADE_MS = 280;
	/** Share of the map the level-0 view fills. */
	const ALL_FILL = 0.8;
	const MIN_RATIO = 0.003;
	const MAX_RATIO = 1.6;

	let container: HTMLDivElement;
	let sigma: Sigma | undefined;
	let graph: Graph | undefined;
	let scheme = $state<Scheme>('light');
	let status = $state<'loading' | 'ready' | 'error'>('loading');
	let nodeCount = $state(0);
	let edgeCount = $state(0);

	const palette = { fg: '#1c2330', bg: '#ffffff', accent: '#1f5fbf' };
	const rootOrder = $derived(new Map([...index.roots].sort().map((id, i) => [id, i])));
	// Plain bookkeeping for the fade-in, read by animation frames: not reactive state.
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	const born = new Map<string, number>();
	let fadeFrame = 0;
	let settleTimer: ReturnType<typeof setTimeout> | undefined;
	let fitted = $state(false);
	/** Pixels per layout unit, refreshed on every camera change. */
	let unitScale = 1;
	let scaleFrame = 0;

	function readPalette() {
		const css = getComputedStyle(document.documentElement);
		palette.fg = css.getPropertyValue('--fg').trim() || palette.fg;
		palette.bg = css.getPropertyValue('--bg').trim() || palette.bg;
		palette.accent = css.getPropertyValue('--accent').trim() || palette.accent;
	}

	function colourOf(id: string, hull: boolean, t = 1): string {
		const topic = index.topics.get(id);
		const rootIndex = rootOrder.get(topic?.rootId ?? id) ?? 0;
		return hull
			? hullColour(rootIndex, scheme, t)
			: bubbleColour(rootIndex, topic?.level ?? 0, scheme, 0.92 * t);
	}

	function setStatus(next: 'loading' | 'ready' | 'error') {
		status = next;
		onstatus?.(next);
	}

	// ---- drawing ----------------------------------------------------------------------------

	function wrap(text: string): string {
		return text.length > 34 ? `${text.slice(0, 33)}…` : text;
	}

	const drawLabel: NodeLabelDrawingFunction = (context, data, settings) => {
		if (!data.label) return;
		const hull = data.zIndex === 0;
		const size = settings.labelSize;
		context.font = `${hull ? 600 : data.zIndex === 1 && data.size > 20 ? 600 : 500} ${size}px ${settings.labelFont}`;
		context.textAlign = 'center';
		context.textBaseline = 'middle';
		const text = wrap(data.label);
		const width = context.measureText(text).width;
		let y: number;
		if (hull) y = data.y - data.size + size + 4;
		else if (width + 10 < data.size * 1.8) y = data.y;
		else y = data.y + data.size + size * 0.9;
		context.lineJoin = 'round';
		context.lineWidth = 4;
		context.strokeStyle = palette.bg;
		context.strokeText(text, data.x, y);
		context.fillStyle = palette.fg;
		context.fillText(text, data.x, y);
	};

	const drawHover: NodeHoverDrawingFunction = (context, data, settings) => {
		context.lineWidth = 3;
		context.strokeStyle = palette.accent;
		context.beginPath();
		context.arc(data.x, data.y, data.size + 2, 0, Math.PI * 2);
		context.stroke();
		drawLabel(context, data, settings);
	};

	// ---- keeping Sigma in step with the props -----------------------------------------------

	function syncGraph() {
		if (!sigma || !graph) return;
		const g = graph;
		// eslint-disable-next-line svelte/prefer-svelte-reactivity
		const want = new Map<string, boolean>(); // id -> is a hull
		for (const id of hulls) want.set(id, true);
		for (const id of bubbles) want.set(id, false);
		for (const id of g.nodes()) if (!want.has(id)) g.dropNode(id);
		const now = performance.now();
		for (const [id, hull] of want) {
			const topic = index.topics.get(id);
			if (!topic) continue;
			const isNew = !g.hasNode(id);
			const attrs = {
				x: topic.x,
				y: topic.y,
				size: topic.r,
				label: topic.name,
				color: colourOf(id, hull, isNew ? 0 : 1),
				zIndex: hull ? 0 : 1,
				forceLabel: hull || topic.level === 0
			};
			if (isNew) {
				g.addNode(id, attrs);
				born.set(id, now);
			} else {
				g.mergeNodeAttributes(id, { ...attrs, color: colourOf(id, hull, fadeOf(id, now)) });
			}
		}

		g.clearEdges();
		const shown = edgeType === 'none' ? [] : edges;
		const weights = normaliseWeights(shown);
		for (const e of shown) {
			if (!g.hasNode(e.from) || !g.hasNode(e.to)) continue;
			const look = edgeAppearance(e.type, scheme, weights.get(e.key) ?? 0, e.confidence);
			g.addEdgeWithKey(e.key, e.from, e.to, {
				type: e.directed ? 'arrow' : 'line',
				px: look.size,
				size: look.size,
				color: look.colour
			});
		}
		for (const link of ghosts) {
			if (!g.hasNode(link.from) || !g.hasNode(link.to)) continue;
			g.addEdgeWithKey(link.key, link.from, link.to, {
				type: 'line',
				px: 1.2,
				size: 1.2,
				color: ghostColour(scheme)
			});
		}
		nodeCount = g.order;
		edgeCount = shown.filter((e) => g.hasEdge(e.key)).length;
		unitScale = pxPerUnit();
		sigma.refresh();
		startFade();
	}

	function fadeOf(id: string, now: number): number {
		const start = born.get(id);
		if (start === undefined) return 1;
		return Math.min(1, (now - start) / FADE_MS);
	}

	function startFade() {
		if (fadeFrame || born.size === 0) return;
		const step = () => {
			fadeFrame = 0;
			if (!graph || !sigma) return;
			const now = performance.now();
			for (const id of [...born.keys()]) {
				if (!graph.hasNode(id)) {
					born.delete(id);
					continue;
				}
				const t = fadeOf(id, now);
				graph.setNodeAttribute(id, 'color', colourOf(id, hulls.includes(id), t));
				if (t >= 1) born.delete(id);
			}
			sigma.refresh();
			if (born.size > 0) fadeFrame = requestAnimationFrame(step);
		};
		fadeFrame = requestAnimationFrame(step);
	}

	// ---- camera -----------------------------------------------------------------------------

	/** Pixels per layout unit at the current zoom. */
	function pxPerUnit(): number {
		if (!sigma) return 1;
		const a = sigma.graphToViewport({ x: 0, y: 0 });
		const b = sigma.graphToViewport({ x: 100, y: 0 });
		const scale = Math.hypot(b.x - a.x, b.y - a.y) / 100;
		return Number.isFinite(scale) && scale > 0 ? scale : 1;
	}

	const clampRatio = (ratio: number) => Math.min(MAX_RATIO, Math.max(MIN_RATIO, ratio));

	/** The camera ratio that fits a box of half-sizes around (cx, cy) in the view. */
	function ratioFor(halfW: number, halfH: number, fill = 0.92): number | null {
		if (!sigma) return null;
		const { width, height } = sigma.getDimensions();
		if (width === 0 || height === 0) return null;
		const target = Math.min((width * fill) / 2 / halfW, (height * fill) / 2 / halfH);
		return clampRatio((sigma.getCamera().getState().ratio * pxPerUnit()) / target);
	}

	function fitTo(
		cx: number,
		cy: number,
		halfW: number,
		halfH: number,
		animate: boolean,
		fill = 0.92
	) {
		const ratio = ratioFor(halfW, halfH, fill);
		if (!sigma || ratio === null) return;
		const camera = sigma.getCamera();
		const to = { x: (cx + EXTENT) / (2 * EXTENT), y: (cy + EXTENT) / (2 * EXTENT), ratio };
		if (animate) camera.animate(to, { duration: 420 });
		else camera.setState(to);
	}

	/** The box around every level-0 bubble: centre and half-sizes. */
	function rootsBox(): { cx: number; cy: number; halfW: number; halfH: number } | null {
		let x0 = Infinity,
			x1 = -Infinity,
			y0 = Infinity,
			y1 = -Infinity;
		for (const id of index.roots) {
			const t = index.topics.get(id)!;
			x0 = Math.min(x0, t.x - t.r);
			x1 = Math.max(x1, t.x + t.r);
			y0 = Math.min(y0, t.y - t.r);
			y1 = Math.max(y1, t.y + t.r);
		}
		if (!Number.isFinite(x0)) return null;
		return { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, halfW: (x1 - x0) / 2, halfH: (y1 - y0) / 2 };
	}

	/** Shows every level-0 bubble. */
	export function fitAll(animate = true) {
		const box = rootsBox();
		// a little room around the bubbles for their labels, which hang below them
		if (box) fitTo(box.cx, box.cy, box.halfW, box.halfH, animate, ALL_FILL);
	}

	/** Centres the camera on a topic's disc (or, for a leaf, on its parent's disc). */
	export function zoomToTopic(id: string, animate = true) {
		const topic = index.topics.get(id);
		if (!topic) return;
		const target =
			topic.children.length > 0 ? topic : (index.topics.get(topic.parentId ?? '') ?? topic);
		fitTo(target.x, target.y, target.r, target.r, animate);
	}

	/** Pans (without zooming) just enough to show the topic when it is near or past an edge. */
	export function ensureVisible(id: string) {
		if (!sigma) return;
		const topic = index.topics.get(id);
		if (!topic) return;
		const { width, height } = sigma.getDimensions();
		const p = sigma.graphToViewport({ x: topic.x, y: topic.y });
		const margin = 40;
		if (p.x > margin && p.x < width - margin && p.y > margin && p.y < height - margin) return;
		sigma
			.getCamera()
			.animate(
				{ x: (topic.x + EXTENT) / (2 * EXTENT), y: (topic.y + EXTENT) / (2 * EXTENT) },
				{ duration: 250 }
			);
	}

	export function zoomBy(factor: number) {
		if (!sigma) return;
		const camera = sigma.getCamera();
		camera.animate({ ratio: clampRatio(camera.getState().ratio / factor) }, { duration: 220 });
	}

	function reportScreen() {
		if (!sigma) return;
		const { width, height } = sigma.getDimensions();
		const scale = pxPerUnit();
		const list: OnScreen[] = [];
		for (const id of [...bubbles, ...hulls]) {
			const t = index.topics.get(id);
			if (!t) continue;
			const c = sigma.graphToViewport({ x: t.x, y: t.y });
			const r = t.r * scale;
			list.push({
				id,
				radiusPx: r,
				visible: c.x + r > 0 && c.x - r < width && c.y + r > 0 && c.y - r < height,
				cx: c.x,
				cy: c.y
			});
		}
		const box = rootsBox();
		const all = box ? ratioFor(box.halfW, box.halfH, ALL_FILL) : null;
		const zoomedIn = all === null || sigma.getCamera().getState().ratio < all * 0.97;
		onscreen(list, { width, height, zoomedIn });
	}

	function onCameraUpdated() {
		onhover(null);
		if (!scaleFrame) {
			scaleFrame = requestAnimationFrame(() => {
				scaleFrame = 0;
				if (!sigma) return;
				unitScale = pxPerUnit();
				sigma.refresh();
			});
		}
		clearTimeout(settleTimer);
		settleTimer = setTimeout(reportScreen, 160);
	}

	// ---- lifecycle --------------------------------------------------------------------------

	onMount(() => {
		let observer: ResizeObserver | undefined;
		let scheme$: MediaQueryList | undefined;
		let dead = false;
		const onScheme = () => {
			scheme = scheme$?.matches ? 'dark' : 'light';
			readPalette();
		};

		void (async () => {
			try {
				const [{ default: SigmaClass }, { default: GraphClass }] = await Promise.all([
					import('sigma'),
					import('graphology')
				]);
				if (dead) return;
				scheme$ = window.matchMedia('(prefers-color-scheme: dark)');
				scheme$.addEventListener('change', onScheme);
				onScheme();

				const g = new GraphClass({ multi: true, type: 'directed' });
				graph = g;
				const s = new SigmaClass(g, container, {
					// the list view hides the map: its container then has no size
					allowInvalidContainer: true,
					autoRescale: false,
					itemSizesReference: 'positions',
					zoomToSizeRatioFunction: (ratio) => ratio,
					zIndex: true,
					renderEdgeLabels: false,
					enableEdgeEvents: false,
					hideEdgesOnMove: false,
					labelRenderedSizeThreshold: 22,
					labelDensity: 8,
					labelGridCellSize: 70,
					labelSize: 12,
					minCameraRatio: MIN_RATIO,
					maxCameraRatio: MAX_RATIO,
					defaultDrawNodeLabel: drawLabel,
					defaultDrawNodeHover: drawHover,
					// Sizes follow the zoom (so that children stay inside their parent's disc); edge
					// thickness is given in pixels and converted here.
					edgeReducer: (_edge, data) => ({ ...data, size: (data.px as number) / unitScale }),
					nodeReducer: (node, data) =>
						node === focusedId || node === selectedId ? { ...data, highlighted: true } : data
				});
				sigma = s;
				s.setCustomBBox({ x: [-EXTENT, EXTENT], y: [-EXTENT, EXTENT] });

				s.on('clickNode', ({ node }) => {
					if (hulls.includes(node)) onhull(node);
					else onbubble(node);
				});
				s.on('doubleClickNode', ({ node, preventSigmaDefault }) => {
					preventSigmaDefault();
					onopen(node);
				});
				s.on('enterNode', ({ node }) => {
					container.style.cursor = 'pointer';
					const t = index.topics.get(node);
					if (!t) return;
					const c = s.graphToViewport({ x: t.x, y: t.y });
					onhover({ id: node, x: c.x, y: c.y, r: t.r * pxPerUnit() });
				});
				s.on('leaveNode', () => {
					container.style.cursor = '';
					onhover(null);
				});
				s.getCamera().on('updated', onCameraUpdated);

				observer = new ResizeObserver(() => {
					if (!sigma || container.clientWidth === 0 || container.clientHeight === 0) return;
					sigma.resize();
					if (!fitted) {
						fitted = true;
						if (startAt && index.topics.has(startAt)) zoomToTopic(startAt, false);
						else fitAll(false);
					}
					sigma.refresh();
				});
				observer.observe(container);
				syncGraph();
				setStatus('ready');
			} catch (error) {
				console.error('The map could not start', error);
				setStatus('error');
			}
		})();

		return () => {
			dead = true;
			observer?.disconnect();
			scheme$?.removeEventListener('change', onScheme);
			clearTimeout(settleTimer);
			if (fadeFrame) cancelAnimationFrame(fadeFrame);
			if (scaleFrame) cancelAnimationFrame(scaleFrame);
			sigma?.kill();
			sigma = undefined;
			graph = undefined;
		};
	});

	// The graph follows the props; only the props are read here, never the Sigma state.
	$effect(() => {
		void [bubbles, hulls, edges, ghosts, edgeType, scheme, index];
		untrack(syncGraph);
	});

	$effect(() => {
		void [selectedId, focusedId];
		untrack(() => sigma?.refresh());
	});
</script>

<div
	class="map"
	bind:this={container}
	aria-hidden="true"
	data-status={status}
	data-fitted={fitted}
	data-node-count={nodeCount}
	data-edge-count={edgeCount}
></div>

<style>
	.map {
		position: relative;
		width: 100%;
		height: 100%;
		min-height: 18rem;
		overflow: hidden;
		touch-action: none;
	}
</style>
