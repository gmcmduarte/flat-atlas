<script lang="ts">
	import { resolve } from '$app/paths';
	import { MEASURED as M, pct } from '#lib/content/measured.js';
	import { formatDate } from '#lib/venues.js';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	const meta = $derived(data.meta);
	const roots = $derived(data.topics.filter((t) => t.level === 0).length);
	const status = $derived(meta?.works_by_tag_status ?? {});
	const weak = $derived((status.low_confidence ?? 0) + (status.untagged ?? 0));
</script>

<svelte:head>
	<title>Methods · The FLAT Atlas</title>
	<meta
		name="description"
		content="How the FLAT Atlas decides which papers belong to which topics, what the confidence numbers mean, and where the method is known to be wrong."
	/>
</svelte:head>

<article class="prose">
	<h1>Methods</h1>
	<p class="lead">
		How a paper gets its topics, how topics are linked and drawn, what the confidence numbers mean,
		and where all of this is known to be wrong. Everything here describes the pilot release
		{#if meta && !meta.fixture}{meta.release} ({formatDate(meta.date)}), tagged with
			{meta.tagger_version}{:else}of the real data{/if}.
	</p>

	<nav aria-label="On this page" class="toc">
		<ul>
			<li><a href="#scope">What is included</a></li>
			<li><a href="#topics">The topic list</a></li>
			<li><a href="#tagging">How a paper gets its topics</a></li>
			<li><a href="#confidence">What the confidence means</a></li>
			<li><a href="#links">Links between topics</a></li>
			<li><a href="#map">The map</a></li>
			<li><a href="#off">What is switched off</a></li>
			<li><a href="#limits">Known limits</a></li>
		</ul>
	</nav>

	<h2 id="scope">What is included</h2>
	<p>
		The pilot takes <strong>every research paper</strong> of five venues (three conference series
		and two earlier names of two of them; see <a href={resolve('/about')}>About</a>). Front matter,
		such as prefaces and tables of contents, is left out. There is no further filter: a paper is in
		the atlas because it appeared at one of these venues, not because a program judged it to be on
		topic. A scope rule for venues that publish much other material, such as general journals, is
		designed but not used yet.
	</p>
	<p>
		The list of papers comes from DBLP. OpenAlex, Crossref and Semantic Scholar add links, citation
		information and identifiers; records are matched to DBLP papers by DOI first and by title and
		year otherwise, and a record that does not fit is dropped. The conference and journal versions
		of one work are merged into one paper that lists all its versions.
		<a href={resolve('/sources')}>Sources</a> has the details.
	</p>

	<h2 id="topics">The topic list</h2>
	<p>
		There are {meta?.topics ?? 'a few hundred'} topics, {roots} of them at the top level. They form a
		tree-like structure in which a topic can have more than one parent (for example, a topic that belongs
		both to automata and to logic). The list was proposed by a program from titles, existing classification
		systems and the papers themselves, and was <strong>reviewed once, by hand</strong>
		by the maintainer; since then it changes only through reviewed edits. Each topic has a name, a description,
		other names it is known by, and a few example papers.
	</p>

	<h2 id="tagging">How a paper gets its topics</h2>
	<p>
		Papers are tagged by a program that runs on the maintainer's computer. It uses only the paper's
		public metadata and, for many papers, an abstract, which it reads there and never publishes. No
		hosted AI service and no paid service is involved.
	</p>
	<ol>
		<li>
			<strong>Evidence.</strong> For each paper and each plausible topic it measures several things:
			whether the topic's characteristic phrases occur in the title; how close the paper is to the
			topic's example papers and to the topic's description (using SPECTER2, a language model for
			scientific papers, which turns a paper into numbers); what OpenAlex says the paper is about;
			and how many of the <em>titles of the papers it cites</em> look like the topic. That last
			signal matters because most abstracts are not available: only about {M.abstractShare} % of the pilot's
			papers have one from any source, while about {M.referenceListShare} % have a reference list.
		</li>
		<li>
			<strong>Combining.</strong> A learned model (gradient-boosted decision trees) combines the
			evidence into one probability per paper and topic. It also learns <em>when</em> to trust which
			evidence: for instance, a missing abstract. A topic's score also depends on how likely its
			parent topic is, but a wrong guess at the top never blocks the topics below it. The pilot uses
			the
			<strong>average of five such models</strong>, each trained with a different random seed,
			because one model was not stable enough: under another random seed it changed the main topic
			of {pct(M.seedChange.single, 1)} of the papers, the average of five changes
			{pct(M.seedChange.bagged)}.
		</li>
		<li>
			<strong>Calibrating.</strong> The probabilities are adjusted so that, on average, a tag with confidence
			70 % is right about 70 % of the time (see below).
		</li>
		<li>
			<strong>Choosing.</strong> A paper gets the most specific topics the evidence supports, up to
			three, each with confidence at least 45 % (both numbers were tuned on the training papers),
			and the strongest is marked as the main one. If only a broad topic is supported, the paper
			gets that. The broader topics above a tag are shown as <em>broader</em> and carry the
			confidence of the specific topic below them. A paper with no topic at 45 % gets its best
			top-level topic if that has at least 15 % and is marked a <strong>weak match</strong>
			({status.low_confidence?.toLocaleString('en') ?? '…'} papers); otherwise it is left
			<strong>not classified yet</strong> ({status.untagged?.toLocaleString('en') ?? '…'} papers).
		</li>
	</ol>
	<p>
		The model was trained and measured on a <strong>labelled set of {M.labelled} papers</strong>,
		plus automatic labels from exact title matches. {M.heldOut} of the labelled papers were kept back
		and looked at once, to compare methods and to measure the final result.
		<strong
			>The labels were drafted by an AI assistant (Claude) and approved by the maintainer without
			changes.</strong
		>
		There was no independent expert labelling and no blind subset, so the numbers below measure agreement
		with that reading, not with the field's experts. No AI service tags papers on the live site.
	</p>
	<!--
		TODO(worked-example): a worked example belongs here: one real paper traced from its evidence to
		its confidence (the output of `flatatlas tag --explain <work>`). Waiting for the maintainer to
		pick the works (PROGRESS.md, "Waiting on Guilherme"). Until then every paper page explains its
		own tags in a sentence under each topic.
	-->
	<p>
		Every paper page already explains each of its tags: the strongest pieces of evidence and their
		scores, the method and the tagger version.
	</p>

	<h2 id="confidence">What the confidence means</h2>
	<p>
		A confidence of 90 % means: of tags that get this score, about 90 % agree with the reference
		labels. It is <strong>not</strong> the chance that a topic is the right place for a paper in any absolute
		sense, and it is not a measure of a paper's quality.
	</p>
	<p>The same held-out papers give these results for the final method:</p>
	<div class="scroll">
		<table>
			<caption class="sr-only"
				>Agreement with the reference labels on {M.heldOut} held-out papers</caption
			>
			<thead>
				<tr
					><th scope="col">Level</th><th scope="col">Precision</th><th scope="col">Recall</th><th
						scope="col">F1</th
					></tr
				>
			</thead>
			<tbody>
				<tr>
					<th scope="row">Top-level topics</th>
					<td
						>{pct(M.level0.precision)} ({pct(M.level0.precisionRange[0])} to {pct(
							M.level0.precisionRange[1]
						)})</td
					>
					<td
						>{pct(M.level0.recall)} ({pct(M.level0.recallRange[0])} to {pct(
							M.level0.recallRange[1]
						)})</td
					>
					<td>{M.level0.f1.toFixed(2)}</td>
				</tr>
				<tr>
					<th scope="row">Subtopics (one level down)</th>
					<td
						>{pct(M.level1.precision)} ({pct(M.level1.precisionRange[0])} to {pct(
							M.level1.precisionRange[1]
						)})</td
					>
					<td
						><strong>{pct(M.level1.recall)}</strong> ({pct(M.level1.recallRange[0])} to {pct(
							M.level1.recallRange[1]
						)})</td
					>
					<td>{M.level1.f1.toFixed(2)}</td>
				</tr>
			</tbody>
		</table>
	</div>
	<p>
		<em>Precision</em>: of the tags shown, the share that agree with the reference. <em>Recall</em>:
		of the reference tags, the share found. In brackets, a 90 % interval. Measured once on release
		{M.release} ({M.tagger}). Subtopic recall is the weak number: about four in ten subtopic
		memberships are missed, so subtopic sizes are underestimated. Calibration is good on average,
		not everywhere: in the same check, tags stated at {M.calibrationBin.stated} were right about {pct(
			M.calibrationBin.observed
		)}
		of the time ({M.calibrationBin.n} tags).
	</p>

	<h2 id="links">Links between topics</h2>
	<p>
		A topic page lists up to ten links of each of three kinds. They are computed from the tagged
		papers, they are <strong>kept apart on purpose</strong>, and their confidences
		<strong>cannot be compared across kinds</strong>.
	</p>
	<ul>
		<li>
			<strong>Related</strong>: papers on one topic are unusually often also on the other (at least
			five papers in both; a normalised co-occurrence score). Confidence is the share of resamplings
			of the papers in which the link survives.
		</li>
		<li>
			<strong>Builds on</strong>: papers of one topic cite papers of the other more than chance
			allows (a shuffling test). Only citations from a paper that is in one topic and not the other,
			to a paper that is in the other and not the first, count. The arrow points to the topic being
			built on. Confidence is one minus the test's p-value. Only
			{M.citationLinks.toLocaleString('en')} citations between the pilot's papers are known, so this kind
			is sparse: {M.edges.buildsOn} links in all.
		</li>
		<li>
			<strong>Shared community</strong>: the same authors write in both topics (a similarity of
			author activity). Confidence is the share of resamplings of authors in which the link
			survives.
		</li>
	</ul>
	<p>
		This release has {M.edges.related} related, {M.edges.buildsOn} builds-on and {M.edges.sharedCommunity.toLocaleString(
			'en'
		)}
		shared-community links.
	</p>

	<h2 id="map">The map</h2>
	<p>
		Each bubble is a topic. Its <strong>size</strong> is the confidence-weighted number of papers
		below it (a paper counts once, however many subtopics it has), and its <strong>colour</strong> is
		its top-level topic. Positions are computed in advance by a force layout on the links between top-level
		topics, so the map looks the same on every visit; subtopics sit inside their parent. A topic with
		several parents is drawn inside its main parent, with a thin grey line to the others. Clicking or
		zooming into a bubble opens its subtopics; a list view and keyboard navigation give the same information
		without the picture.
	</p>

	<h2 id="off">What is switched off, and why</h2>
	<p>
		Two ideas were built and tested and <strong>are not used</strong> in the pilot, because on the held-out
		papers they did not help beyond noise:
	</p>
	<ul>
		<li>
			a local open language model that answered yes/no questions about the papers the learned model
			was unsure of (a small gain, +0.014 in F1, with an interval that includes zero, at the cost of
			hours of computing per run);
		</li>
		<li>
			spreading topics along citations and between co-authors (also +0.014, interval including zero;
			the citation graph is too thin).
		</li>
	</ul>
	<p>
		The choice follows a rule written down before the held-out papers were opened: keep the simpler
		method unless the more complex one is clearly better. Both can be tried again with more data.
	</p>

	<h2 id="limits">Known limits</h2>
	<ul>
		<li>
			<strong>A narrow slice.</strong> Five venues, all conference proceedings, from 1993. Work published
			elsewhere is missing, and the picture of the field is the picture these venues give.
		</li>
		<li>
			<strong>Tags are automatic and often right, not always.</strong>
			About {weak.toLocaleString('en')} of {meta?.works.toLocaleString('en') ?? '…'} papers have only
			a weak match or none. Topic assignments are guesses with a stated confidence; please report mistakes.
		</li>
		<li>
			<strong>Subtopic recall is {pct(M.level1.recall)}.</strong> Counts and bubble sizes below the top
			level are lower than the truth.
		</li>
		<li>
			<strong>Little text.</strong> Most papers have only a title and the titles of what they cite to
			go on.
		</li>
		<li>
			<strong>Reference labels are not independent.</strong> They were drafted by an AI assistant
			and approved by one person. {M.heldOut} held-out papers can only resolve differences of about three
			points.
		</li>
		<li>
			<strong>Citations</strong> are known only between papers inside the atlas, and the citation
			graph is thin ({M.citationLinks.toLocaleString('en')} links), so "builds on" links are few and cautious.
		</li>
		<li>
			<strong>Authors</strong> are identified by their DBLP person ID. A person with two IDs appears twice,
			and two people merged under one ID appear once. There are no affiliations on the pages.
		</li>
		<li>
			<strong>Pages show a selection.</strong> A topic page lists its {M.topicPagePapers} best-ranked
			papers; a venue page shows top-level topics only; search finds the name shown on an author page,
			not other spellings.
		</li>
		<li>
			<strong>These numbers are a snapshot</strong>, measured on release {M.release}. A new release
			or a new tagger version means new measurements.
		</li>
	</ul>
	<p class="note">
		Found something wrong? Every topic, paper, author and venue page ends with a link to a GitHub
		form with the page's details filled in.
	</p>
</article>

<style>
	.toc ul {
		columns: 14rem;
		padding-left: 1.1rem;
		margin: 0.5rem 0 0;
	}
</style>
