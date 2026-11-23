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
COPYFILE_DISABLE=1 tar -czf site-data.tar.gz -C web/static data
gh release create site-data-v2026.11.0 site-data.tar.gz \
  --title "Site data v2026.11.0" --notes "Static export of release v2026.11.0 (metadata only)."
```
The archive must hold a top-level `data/` folder (the workflow checks for `data/meta.json`). On macOS `COPYFILE_DISABLE=1` keeps `._*` files out of it (macOS `tar` hides them when listing, so check with `python3 -c "import tarfile; print([n for n in tarfile.open('site-data.tar.gz').getnames() if '/._' in n])"`, which must print `[]`); the workflow and the venue page entries also ignore them. Use one
release tag per export; an existing tag is updated with `gh release upload <tag> site-data.tar.gz --clobber`.

## 4. Tell the Pages workflow to use it
Repository **Settings → Secrets and variables → Actions → Variables**: set `SITE_DATA_TAG` to the
tag (for example `site-data-v2026.11.0`). The next run of the Pages workflow (a push to `main`, or
"Run workflow") downloads the archive into `web/static/`, builds with `PUBLIC_DATA_DIR=data` and
deploys. To go back to the fixture, delete the variable.

## 5. The launch order (P1-12)
These are the steps that are yours; none of them is done by a coding session.
1. Merge the P1-12 pull request. Pages redeploys from `main` on the fixture (the issue forms in
   `.github/ISSUE_TEMPLATE/` only work once they are on `main`).
2. From the repository root, on `main`: `uv run flatatlas export static` (reads the existing verified
   release; `meta.json` now lists the venues, so an export made before P1-12 is out of date), then
   steps 2 and 3 above. Check the archive: `tar -tzf site-data.tar.gz | grep data/meta.json`.
3. Set the variable `SITE_DATA_TAG` (step 4) and run the Pages workflow.
4. Look at the live site: the banner names release, date and venues; open a topic, a paper, an author
   and a venue; click one "Suggest a change" link and check that the GitHub form opens with the entity
   filled in.
5. Tag the code: `git checkout main && git pull && git tag -a v0.1.0 -m "Pilot release v0.1.0" && git push origin v0.1.0`.
   `v0.1.0` is the version of the code and site (`CITATION.cff`); `v2026.11.0` is the data release and
   `site-data-v2026.11.0` the release that carries its export. They are three different tags.
6. Optional: create the labels `suggestion`, `wrong-tag`, `missing-paper`, `author`, `new-topic`,
   `venue` (issue forms ignore labels that do not exist); upload the repository social preview
   (`web/static/og.png`) in Settings; link the repository to Zenodo for a DOI.

## Notes
- The release is public: do not attach anything that is not in `web/static/data/`.
- Updating the site means a new release asset and a new tag in the variable; the workflow does not
  look for newer releases by itself.
- CI never needs the warehouse: it builds on the fixture and runs the Playwright smoke test on it.
