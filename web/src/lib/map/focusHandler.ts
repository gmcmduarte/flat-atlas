/**
 * The bridge between the header search (in the layout) and the map (on the home page): the map
 * registers a handler while it is on screen; the search offers every topic choice to it first.
 */
type Handler = (topicId: string) => boolean;

let current: Handler | null = null;

/** Registers the map's handler; returns the function that removes it. */
export function registerMapFocus(handler: Handler): () => void {
	current = handler;
	return () => {
		if (current === handler) current = null;
	};
}

/** True when a map took the topic. */
export function focusMapOn(topicId: string): boolean {
	return current ? current(topicId) : false;
}
