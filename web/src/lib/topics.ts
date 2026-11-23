import type { Topic } from './data/types';

/**
 * Every path from a top-level topic down to `topicId` (excluding the topic itself): one per way
 * of reaching it, since a topic can have several parents (PLAN §11.3, breadcrumbs for each
 * parent path). Paths are ordered by the parents' order in the data; a cycle is cut.
 */
export function ancestorPaths(topics: Topic[], topicId: string): Topic[][] {
	const byId = new Map(topics.map((t) => [t.topic_id, t]));
	const walk = (id: string, seen: Set<string>): Topic[][] => {
		const topic = byId.get(id);
		if (!topic || seen.has(id)) return [];
		if (topic.parents.length === 0) return [[topic]];
		const next = new Set(seen).add(id);
		const paths = topic.parents.flatMap((parent) => walk(parent, next));
		return paths.length === 0 ? [[topic]] : paths.map((path) => [...path, topic]);
	};
	const topic = byId.get(topicId);
	if (!topic) return [];
	return topic.parents
		.flatMap((parent) => walk(parent, new Set([topicId])))
		.filter((path) => path.length > 0);
}
