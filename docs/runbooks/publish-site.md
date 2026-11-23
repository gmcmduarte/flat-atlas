# Publish the site with real data

The Pages workflow builds the site from the **fixture** (`web/static/data-fixture/`) unless a
repository variable names a release that carries the real export. Nothing real is published until
you do the steps below; the data never enters git (`web/static/data/` is ignored).

## 1. Produce the export locally
From the repository root:

```bash
uv run flatatlas aggregate && uv run flatatlas release build && uv run flatatlas export static
```

This writes `web/static/data/` (about 10 MB, 700 files) from the latest folder in
`data/releases/`. It contains metadata only: no abstracts, no TLDRs (rule 2).

## 2. Look at it before it goes public
```bash
cd web && PUBLIC_DATA_DIR=data npm run build && npm run preview
```
Open a topic, a paper, an author and a venue; search for a topic and a name. The footer shows the
release and its date.

## 3. Pack it and attach it to a GitHub release
```bash
tar -czf site-data.tar.gz -C web/static data
gh release create site-data-v2026.11.0 site-data.tar.gz \
  --title "Site data v2026.11.0" --notes "Static export of release v2026.11.0 (metadata only)."
```
The archive must hold a top-level `data/` folder (the workflow checks for `data/meta.json`). Use one
release tag per export; an existing tag is updated with `gh release upload <tag> site-data.tar.gz --clobber`.

## 4. Tell the Pages workflow to use it
Repository **Settings → Secrets and variables → Actions → Variables**: set `SITE_DATA_TAG` to the
tag (for example `site-data-v2026.11.0`). The next run of the Pages workflow (a push to `main`, or
"Run workflow") downloads the archive into `web/static/`, builds with `PUBLIC_DATA_DIR=data` and
deploys. To go back to the fixture, delete the variable.

## Notes
- The release is public: do not attach anything that is not in `web/static/data/`.
- Updating the site means a new release asset and a new tag in the variable; the workflow does not
  look for newer releases by itself.
- CI never needs the warehouse: it builds on the fixture and runs the Playwright smoke test on it.
