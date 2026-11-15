# The FLAT Atlas

An open, public map of **formal languages and automata theory** from the 1950s to today.

The Atlas links topics, papers, authors and venues so that researchers and students can:

- search a topic and see its papers, parent and child topics, related topics, key authors and activity over time;
- travel from general topics to specific ones, and sideways to related ones;
- see the whole field as a map;
- compare venues with transparent, side-by-side metrics.

**Status:** Phase 0 (foundations) in progress: the project scaffold, CLI and CI exist; no data or site yet. See [`docs/plan/PROGRESS.md`](docs/plan/PROGRESS.md).

## How it works

- Metadata comes from open sources: [DBLP](https://dblp.org), [OpenAlex](https://openalex.org), [Semantic Scholar](https://www.semanticscholar.org) and [Crossref](https://www.crossref.org). The Atlas stores metadata and links only, never full texts.
- The topic map and all topic tags are produced automatically, with a confidence score and the method that produced them.
- Everything is free to use and costs nothing to run.

## Documentation

| Document | Content |
|---|---|
| [`docs/plan/PLAN.md`](docs/plan/PLAN.md) | Architecture, data model, taxonomy and tagging method |
| [`docs/plan/ROADMAP.md`](docs/plan/ROADMAP.md) | Phases and build sessions |
| [`docs/plan/DECISIONS.md`](docs/plan/DECISIONS.md) | Decision log |
| [`docs/plan/RISKS.md`](docs/plan/RISKS.md) | Risks and mitigations |

## Development

Needs [uv](https://docs.astral.sh/uv/); uv installs the pinned Python (3.12) by itself.

```bash
uv sync                      # create .venv and install the locked dependencies
uv run flatatlas --help      # the pipeline CLI
uv run pytest                # tests
uv run ruff check .          # lint
uv run ruff format .         # format
uvx pre-commit install       # once: run the hooks (ruff, gitleaks) on every commit
uvx pre-commit run --all-files
```

The site in `web/` needs Node 22.17 or newer (CI uses 24): `cd web && npm ci && npm run dev`; see `web/README.md`.

API keys go in `.env` (git-ignored); copy `.env.example` and fill it in. Never commit real values.

## Corrections

Found a wrong tag, a missing paper or a duplicated author? Please open an issue.

## Licence

Code: MIT (see [`LICENSE`](LICENSE)). Data releases: CC BY 4.0, with attribution to the sources. Details in `docs/plan/PLAN.md` §10.

## Maintainer

Guilherme Duarte.
