# Source behaviour observed in practice

Dated observations from live use. `config/sources.yaml` holds the settings; this file holds the
evidence. Newest first within each source.

## DBLP

- **2026-11-15 (P0-03): bot challenge.** `dblp.org`, `dblp.uni-trier.de` and `dblp.dagstuhl.de`
  answer API requests (`/search/venue/api?...&format=json`) with HTTP 202 and an Anubis
  proof-of-work page instead of JSON. Not solved on purpose (bypassing bot detection). The
  client raises `SourceError: dblp: HTTP 202 ...`. Consequence: the DBLP API cannot be used from
  scripts as things stand; see `venues-pilot.md` for the options. P1-01 depends on the outcome.
- Rate-limit behaviour could not be observed (no successful call). `requests_per_second: 1.0`
  in `config/sources.yaml` stays as the conservative value.

## OpenAlex

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
- Still unverified (P1-02): max DOIs per `filter=doi:`, `from_updated_date` on the free key.
