# Source behaviour observed in practice

Dated observations from live use. `config/sources.yaml` holds the settings; this file holds the
evidence. Newest first within each source.

## DBLP

- **2026-11-15 (P0-03): bot challenge on the API.** `dblp.org`, `dblp.uni-trier.de` and
  `dblp.dagstuhl.de` answer API requests (`/search/venue/api?...&format=json`) with HTTP 202 and
  an Anubis proof-of-work page instead of JSON. Not solved on purpose (bypassing bot detection).
  `SourceClient` raises `SourceError: dblp: HTTP 202 ...`. Nothing from the DBLP API is cached.
  Consequence: DBLP data comes from the XML dump (D-49). The `dblp` entry of `config/sources.yaml`
  is unused for now.
- **2026-11-15: the dump.** `dblp.xml.gz` 1,120,092,202 bytes (MD5 `4316d8f5...`), 128,293,598
  lines, 13,108,712 records, ISO-8859-1 with named entities defined in `dblp.dtd`
  (65 numeric-character entities, read by regular expression). A full streaming pass through
  `flatatlas.dblp_dump` takes about 100 s and constant memory. Top-level tags: `article`,
  `inproceedings`, `proceedings`, `book`, `incollection`, `phdthesis`, `mastersthesis`, `www`,
  `data` (the DTD also allows `person`; the dump has none). The file is grouped by type, not by venue, and has no release date inside.
- Record shapes seen: a `proceedings` record has `editor`, `title`, `booktitle`, `publisher`,
  `year` (publication year), `series`, `volume`, `isbn`, `ee` (the volume DOI) and `url`
  (`db/conf/dlt/dlt2019.html`); a paper has `author` (name only, homonyms as `Name 0001`, ORCID
  as an attribute), `title`, `pages`, `year`, `booktitle`, `ee` (DOI), `crossref` (the edition
  key) and `url`. Author PIDs are not on papers: person records are `<www key="homepages/226/0821">`
  (PID `226/0821`) with the name variants as `author` children; mapping is for P1-01.

## OpenAlex

- **2026-11-15 (P1-02): limits checked live.** (a) `filter=doi:a|b|...` takes at most **100**
  values: 50 and 100 DOIs returned 50 and 100 works (HTTP 200, `per_page=200`), 101 and 150 gave
  HTTP 400. The filter value is `https://doi.org/<doi>`. (b) A 100-DOI list call cost USD 0.0001
  (`x-ratelimit-cost-usd`), so the 2,024 pilot DOIs cost about USD 0.0021. (c)
  **`from_updated_date` is not available on the free key:** it answered HTTP 429 (alone and
  combined with a DOI filter), while plain list calls two seconds apart returned 200. The
  OpenAlex help page for work filters says `from_updated_date` and `from_created_date` need a
  paid plan ("429 ... Plan upgrade required"). PLAN §5.3 already has the fallback: re-fetch by
  DOI. (d) The help page says a free key gets **30 requests/s**; I did not measure it and keep
  10/s in `config/sources.yaml`. (e) Docs and headers: `X-RateLimit-Credits-Used` is named in
  the docs; the headers seen on the wire are `x-ratelimit-cost-usd`, `x-ratelimit-remaining`,
  `x-ratelimit-remaining-usd`. (f) The docs moved from `docs.openalex.org` to
  `help.openalex.org`.
- **2026-11-15 (P0-03): key parameter.** `api_key=<key>` as a query parameter is accepted
  (HTTP 200). `x-ratelimit-*` response headers: `x-ratelimit-limit: 10000` credits per day,
  `x-ratelimit-limit-usd: 1`, `x-ratelimit-remaining`, `x-ratelimit-remaining-usd`,
  `x-ratelimit-reset` (seconds until reset), `x-ratelimit-cost-usd` per call. A `list`
  call (`/works?filter=...`) cost 1 credit (USD 0.0001), matching `costs.list` in
  `config/sources.yaml`. A `search` call (`/sources?search=...`) is configured at USD 0.001
  (10 credits); the headers were not compared for search calls. The local ledger and the
  server counters agreed to within the calls made in the session (about USD 0.023 spent).
- `GET /sources?search=<name>`: matches names but not acronyms reliably ("DCFS" found a source,
  "CIAA" found nothing). `select=` works on `/sources` and `/works`.
- Per-second rate with a key: not measured (the session made 29 calls at the configured
  10/s; no 429).
