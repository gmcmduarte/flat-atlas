# Source behaviour observed in practice

Dated observations from live use. `config/sources.yaml` holds the settings; this file holds the
evidence. Newest first within each source.

## Licences as published on the site (P1-12, 2026-11-23)

What the site's Sources page says, and where each line comes from. **Copied from PLAN §3 and D-15
(checked 2026-11-15); the licence pages were not re-read in P1-12.** Re-read them before the first
dataset release (Zenodo).

| Source | Licence stated on the site | Basis |
|---|---|---|
| DBLP | CC0 1.0 | PLAN §3 |
| OpenAlex | CC0 | PLAN §3 |
| Crossref | bibliographic metadata, no copyright claimed by Crossref; abstracts are not used on the site | PLAN §3 ("treated as facts") |
| Semantic Scholar | data ODC-BY 1.0, embeddings Apache 2.0; "Semantic Scholar" named; Kinney et al. 2023 cited (arXiv:2301.10140, number from memory, not re-checked) | PLAN §3, §10 |
| ACM CCS | ACM keeps the copyright; free for educational and research purposes; seed only, nothing redistributed | this file, "ACM CCS download" |
| SPECTER2 | no licence stated: "see the model card" (the licence of `allenai/specter2` is not recorded here) | gap |
| Qwen3-8B (decision model) | not mentioned on the site: the step is off (D-100) and no output of it is shipped | D-100 |
| Atlas code / data | MIT / CC BY 4.0 (data release intended, not yet published) | D-15 |

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

- **2026-11-16 (P1-05): titles of cited works.** (a) The route chosen is **OpenAlex ID batches**,
  `GET /works?filter=openalex:W1|W2|...&select=id,title,publication_year,type&per_page=100`
  (the filter name `openalex` checked live; 100 IDs per call, USD 0.0001 a call). A probe of
  100 IDs returned 99 works. The full run asked the **15,135** candidate IDs of
  `stg_reference_candidates` in **152 calls, USD 0.0152**, and got **14,797** works back (338, or
  2.2 %, not returned; 1 returned without a title). With the 856 pilot works that are cited by
  other pilot works, **36,250 of the 37,024 reference edges (97.9 %)** have a title. (b) The S2
  route (`references.title` in the batch) was not used: it changes every cache key, needs a second
  pass of about 2 hours at the current throttling, and only 23 % of S2 papers have reference
  lists at all. (c) **Background titles:** `sample=<n>&seed=<k>&per_page=200&page=<p>` pages like a
  normal list (page 2 of a 400-sample returned the next 200); 25 calls gave 5,000 works, 4,993
  with a title. Negated filters work: `primary_topic.id:!T11269` (repeat the filter for each
  value). Subfield IDs checked: `1703` Computational Theory and Mathematics (954,659 works),
  `2614` Theoretical Computer Science (90,247). The background is a seeded sample of articles of
  these two subfields from 1995 to 2025, minus the seven topics most pilot works have as their
  primary topic (`config/taxonomy.yaml`). It is mathematics-flavoured theory (graphs, matrices,
  optimisation), a broad contrast rather than a close one.
- **ACM CCS download:** `https://dl.acm.org/ccs` answered HTTP 403 to an automated fetch (checked
  2026-11-16), so `flatatlas taxonomy seeds --ccs-file` reads a SKOS file that a person saves from
  that page (default `data/raw/seeds/acm-ccs.xml`; done on 2026-11-16: 2,113 concepts, 13 kept). The ACM page states that the CCS is free to use
  for educational and research purposes; ACM keeps the copyright.

## Semantic Scholar

- **2026-11-16 (P1-03): checked live with our key.** (a) `POST /graph/v1/paper/batch?fields=...`
  takes at most **500** IDs: 500 returned 500 answers, 501 gave HTTP 400. A 500-ID answer with the
  full field list is about 6 MB of JSON and took 11 s. (b) Accepted ID prefix: **`DOI:`**. **`DBLP:<key>` is not
  accepted**: it answers `null` in the batch even for a paper S2 holds (the same paper was found
  by its DOI, and its `externalIds.DBLP` shows that key). So papers without a DOI, and papers S2
  does not know by DOI, go through `GET /paper/search/match?query=<title>` (best title match, one
  call each; no hit is HTTP 404 and is cached). The match answer has the same fields as the batch.
  (c) The field name is **`embedding.specter_v2`**: the answer is `{"model": "specter_v2",
  "vector": [768 floats]}`, or `null`. (d) `references.corpusId` works; **`references.isInfluential`
  gives HTTP 400** in a batch, so the per-edge "influential" flag cannot be had this way (it
  exists on `/paper/{id}/references`, one call per paper, and in the datasets). Per-paper
  `influentialCitationCount` is available. (e) Always returned, whatever is asked: `paperId`,
  `authors`, `openAccessPdf`. For Springer papers `openAccessPdf.disclaimer` says the publisher
  elided `abstract` and `references`: **abstract is null for most pilot papers and the reference
  list is null for about 77 %** of the S2 papers (518 of 2,257 have one). A `null` list is stored
  as `n_references` null, never as zero.
- **Rate limit: the documented 1 request/s is not what we get.** With the key set, a sustained
  run drew HTTP 429 on 15 to 25 % of calls at 5 s spacing, and about **1.3 to 2 per success** at
  1/s and at 0.5/s. A lighter request (fewer fields) was no better. The 429 body is the generic
  "Too Many Requests ... apply for a key" and there are no `Retry-After` or rate-limit headers.
  It looks like server-side throttling, not our rate. Two runs at 1/s with six attempts died
  after six 429s in a row (title match 55 of 724). Config now: 0.5/s and `max_attempts: 10`
  (back-off 1, 2, 4, 8, 16, 32, 60 s ..., about 4 minutes). The resumed run did 637 title matches
  in **1 h 53 min** (838 logged 429s), about 10.6 s per match; the DOI batches (5 calls) take a
  minute. Budget a title-match job at roughly 11 s per paper.
- **Match quality.** Accepted at title similarity >= 0.95 and year within 1 of the DBLP edition
  (the OpenAlex rule): 645 of 724 asked papers matched (89 %), average similarity 1.0, lowest
  0.95. Of 2,260 matched papers, **354 point to another
  DBLP key** in S2's own `externalIds.DBLP` (220 via title match, 134 via DOI): S2 has merged the
  conference paper with its journal or CoRR version. They are kept, with the other key stored in
  `stg_s2_lookup.s2_dblp_key`, for P1-04's version merging (PLAN §8.2).
- **`references.title` and `references.year` are accepted** in a batch (checked 2026-11-16 on one
  paper: 34 references, each `{paperId, corpusId, title, year}`; `corpusId` inside a reference is a
  string). P1-03 did not ask for them, so the cached answers hold reference IDs only; asking now
  changes the field list and so the cache keys (a new full pass, about 2 hours with title matches,
  or about a minute for the DOI batches alone). Only about 23 % of the S2 papers have a reference
  list at all.
- **TLDRs** are returned for most papers (1,831 of 2,257) and kept in
  `stg_s2_paper.tldr` (staging is never exported).

## SPECTER2 on this Mac (Hugging Face)

- **Model:** base `allenai/specter2_base` plus the proximity adapter **`allenai/specter2`**
  (renamed on Hugging Face; the model card of 2026-11-16 loads it with `adapters`:
  `model.load_adapter("allenai/specter2", source="hf", load_as="proximity", set_active=True)`).
  Vector = first-token state of the last layer, 768 floats. Input `title + [SEP] + abstract`.
  `adapters` logs "adapters available but none are activated" once while loading; it is
  harmless (`model.active_adapters` is `Stack[proximity]` afterwards, and the encoder refuses to
  run if it is empty). Without the adapter the cosine to S2's vectors drops from 0.997 to 0.939.
- **Download:** about 843 MB in `~/.cache/huggingface` (base model plus adapter); torch,
  transformers and adapters add about 0.9 GB to `.venv`. Versions at the time: torch 2.15.0,
  transformers 4.57.6.
- **Throughput on the M1 (batch 32, encoder time only):**

  | Device | Title and abstract (median 687 characters) | Title only (median 52 characters) |
  |---|---|---|
  | `mps` | 18.8 texts/s | 82 texts/s |
  | `cpu` | 9.0 texts/s | 119 texts/s |

  The full pilot run embedded 888 texts (mostly titles) at 127 texts/s (7 s). For the whole
  field (PLAN §17 item 9) that is about 0.5 s per 10 abstract texts; titles are cheap. `cpu` is
  faster than `mps` for very short texts (launch overhead), so `embedding_device` matters only
  for abstracts.
- **Local against S2 vectors** (50 papers that have both): mean cosine **0.980**; papers with an
  abstract 0.999, title only 0.960 (min 0.926). The model-card form for no abstract
  (`title[SEP]`) gives 0.958, so title alone is kept. Likely cause of the gap for title-only
  papers: S2 holds abstracts that its API hides for Springer papers and embedded them
  (not tested). `reports/embedding-compare-pilot.md`.

## Qwen3-8B (GGUF) for the local decision model (P1-07b)

- **What:** `Qwen3-8B-Q4_K_M.gguf`, the 4-bit (Q4_K_M) quantised build of Qwen3-8B published by the
  Qwen team in `Qwen/Qwen3-8B-GGUF` on Hugging Face. Downloaded on 2026-11-19 with Guilherme's
  approval, with `curl` (no library download) into `data/models/llm/qwen3-8b-q4km/` (git-ignored).
- **Size and hash:** 5,027,783,488 bytes (5.03 GB). SHA-256
  `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`, the value Hugging Face lists
  for the file; the downloaded file matches it. This hash goes into the provenance of every cached
  answer and every tag the decision model touched.
- **Licence:** Apache-2.0 (the model card's licence field; the repository's `LICENSE` file is the
  full Apache License 2.0 text, 11.5 kB, read). It allows use, modification and redistribution with
  attribution and the licence text; nothing here is redistributed (the weights stay local, and only
  probabilities derived from them enter the tags). If the model name is shown on the site, cite
  "Qwen3, Qwen Team, Alibaba Cloud".
- **Runtime:** `llama-cpp-python` 0.3.37 (MIT), which bundles llama.cpp, in the optional `llm`
  extra. On this Mac it only built with Apple's compiler: Homebrew's LLVM is first on the path
  (`CPPFLAGS`/`LDFLAGS` point at it) and fails on the Metal sources, so install with
  `CC=/usr/bin/clang CXX=/usr/bin/clang++ CMAKE_ARGS="-DGGML_METAL=on -DGGML_OPENMP=OFF" uv sync --extra ml --extra llm`
  (about 70 s).
- **How it is used:** one forward pass over a prompt, then the logits of the option tokens (letters
  or Yes/No) are read; nothing is generated and no network is used. Qwen3 is a hybrid reasoning
  model; the chat template is filled with an empty think block so the answer comes first.
- **Not used:** any hosted model (D-67 is not active). Newer Qwen releases appear in community
  listings; only the official `Qwen3-8B-GGUF` card was read and verified.
