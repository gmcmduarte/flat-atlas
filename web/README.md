# web: the FLAT Atlas site

SvelteKit + TypeScript, static output (`adapter-static`), deployed to GitHub Pages by
`.github/workflows/pages.yml`. Design: `docs/plan/PLAN.md` §11.

```bash
npm ci               # install
npm run dev          # dev server
npm run check        # svelte-check
npm run lint         # prettier + eslint
npm test             # vitest
npm run build        # static site in build/
BASE_PATH=/flat-atlas npm run build   # as on Pages (https://<user>.github.io/flat-atlas/)
```

## Data

Pages read data through the `DataSource` interface (`src/lib/data/`). `StaticDataSource` reads JSON
from `static/<PUBLIC_DATA_DIR>/` (default `data-fixture`, a small hand-written fixture with
made-up works and authors, all flagged `"fixture": true`). `ApiDataSource` is a stub for the
server stage. Settings (`PUBLIC_DATA_SOURCE`, `PUBLIC_DATA_DIR`) are declared in `src/env.ts` and
read at build time.

Files in `static/data-fixture/` follow PLAN §11.2: `topics.json`, `topic/<id>.json`,
`works/<shard>.json`, `authors/<shard>.json`, `venue/<id>.json`, `map.json`. A shard is the first
two hex characters of the SHA-256 of the ID (`shardOf` in `StaticDataSource.ts`); the pipeline must
use the same rule.

## Images

`static/favicon.svg`, `static/apple-touch-icon.png` (rendered from the favicon), `static/og-source.svg`
and `static/og.png` (the social preview, rendered from `og-source.svg` with the Chromium of
Playwright) are original artwork of this project, drawn from plain shapes: no third-party image,
icon or font is used, and the images contain no text. They are published under the same licences as
the repository (code MIT). Do not add third-party artwork without a licence note here.

## Site address

`src/lib/site.ts` holds the public address (`SITE_URL`, `SITE_BASE`) and the repository. They end up
in the `og:` and canonical tags and in the pre-filled "Suggest a change" links (`src/lib/suggest.ts`
puts only public values in those links). A custom domain means editing that file.
