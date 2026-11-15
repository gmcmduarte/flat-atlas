import { render, screen, within } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import TopicList from './TopicList.svelte';
import type { Topic } from '#lib/data/index.js';

const topics: Topic[] = [
	{
		topic_id: 'automata-theory',
		name: 'Automata theory',
		description: 'Abstract machines that read words.',
		level: 0,
		parents: [],
		children: ['finite-automata'],
		paper_count: 7
	},
	{
		topic_id: 'finite-automata',
		name: 'Finite automata',
		description: 'Machines with finitely many states.',
		level: 1,
		parents: ['automata-theory'],
		children: [],
		paper_count: 4
	}
];

describe('TopicList', () => {
	it('links each topic to its page and lists its subtopics', () => {
		render(TopicList, { topics });
		const main = screen.getByRole('link', { name: 'Automata theory' });
		expect(main.getAttribute('href')).toMatch(/\/topic\/automata-theory$/);
		const subtopics = screen.getByRole('list', { name: 'Subtopics of Automata theory' });
		const sub = within(subtopics).getByRole('link', { name: 'Finite automata' });
		expect(sub.getAttribute('href')).toMatch(/\/topic\/finite-automata$/);
		expect(screen.getByText('7 papers')).toBeTruthy();
	});

	it('names subtopics that are not in the listed topics', () => {
		render(TopicList, { topics: topics.slice(0, 1), allTopics: topics });
		expect(screen.getByRole('link', { name: 'Finite automata' })).toBeTruthy();
	});

	it('says so when there are no topics', () => {
		render(TopicList, { topics: [] });
		expect(screen.getByText('No topics yet.')).toBeTruthy();
	});
});
