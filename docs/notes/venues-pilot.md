# Pilot venues: verification notes (P0-03)

Session date: 2026-11-15. DBLP facts come from the DBLP XML dump; OpenAlex facts from live calls
through `flatatlas.http.SourceClient`. Entries in `config/venues.yaml` carry
`verified: {dblp, openalex}` dates that match this note.

## Summary

| Venue | DBLP stream | Editions in DBLP (conference years) | OpenAlex source IDs |
|---|---|---|---|
| DLT | `conf/dlt` | 31 listed: 1993 to 2026, biennial until 1999 (the 30th is 2026); one stray, see below | S4306418189 |
| WIA (predecessor of CIAA) | `conf/wia` | 4: 1996 to 1999 (1st to 4th) | none found |
| CIAA | `conf/wia` | 26: 2000 to 2026 (5th to 30th), none in 2020 | S4306419526 |
| DCAGRS (predecessor of DCFS) | `conf/dcfs` | 1: 2001 (the 3rd workshop) | none found |
| DCFS | `conf/dcfs` | 22: 2002 to 2026 (4th to 27th), none in 2009, 2010, 2024 | S4306507593, S4306418178 |

Reproduce the DBLP column with `uv run flatatlas venues scan-dump` and `uv run flatatlas venues show <id>`.

## DBLP

### The API is blocked; the dump is used (D-49)

A plain request to the DBLP API (`GET /search/venue/api?q=DLT&format=json`, with or without a
descriptive User-Agent) returns **HTTP 202** with an HTML page ("Making sure you're not a bot!")
carrying an Anubis proof-of-work challenge. Same on `dblp.org`, `dblp.uni-trier.de` and
`dblp.dagstuhl.de`. Solving it from a script would be bypassing bot detection, so it was not
attempted. DBLP data comes from the official dump instead, downloaded by hand.

### The dump used

| | |
|---|---|
| Files | `data/raw/dblp-dump/dblp.xml.gz`, `dblp.dtd`, `dblp.xml.gz.md5` (git-ignored) |
| Downloaded | 2026-11-15 by Guilherme |
| Size | 1,120,092,202 bytes compressed; 128,293,598 lines; 13,108,712 records |
| MD5 | `4316d8f583ba373af170da805e7c46bf`, matches the `.md5` file |
| Newest record date in the five streams | 2026-11-07 (`mdate`) |
| Licence | CC0 1.0 (header of the DTD) |
| Read by | `flatatlas.dblp_dump`: a stream through `gzip` and `xml.etree`; the DTD's entities are read as a dictionary and the external DTD is never loaded; about 100 s for a full pass |

### Method

1. A line scan of the whole dump for `<proceedings>` records whose title mentions the venue names
   (and their acronyms, workshop names and the "FDSR" name from PLAN §7.1) to find the stream
   keys. This is how it was found that there is no `conf/ciaa` and no `conf/dcagrs`, and no FDSR
   stream.
2. `flatatlas venues scan-dump`: for each stream in `venues.yaml`, every `proceedings` record and
   every key cited in a paper's `crossref` is an edition. An edition's year is the last part of
   its key (`conf/dlt/2019`), because the `year` of a proceedings record is the *publication*
   year (`conf/dlt/2025` has year 2026).
3. Titles of the edition records were read to confirm the numbering (1st to 30th) and the names.

### Findings (these correct PLAN §7.1, which has been edited)

- **CIAA has no stream of its own.** DBLP keeps WIA (1996 to 1999) and CIAA (2000 on) together in
  `conf/wia`: WIA'96 to WIA'99 are the 1st to 4th workshops; CIAA 2000 (London, Ontario) is the
  5th; the 30th is CIAA 2026. There is no 2020 edition (24th in 2019, 25th in 2021). Because two
  venues share the stream, `venues.yaml` gives each a year range (D-50).
- **DCFS and DCAGRS likewise share `conf/dcfs`.** `conf/dcfs/2001` is "Third International
  Workshop on Descriptional Complexity of Automata, Grammars and Related Structures - DCAGRS
  2001, Vienna". From the 4th workshop (2002, London, Ontario) the name is DCFS; the 27th is DCFS
  2026. DBLP has **no** records for the first two DCAGRS workshops. PLAN's "since about 1999 as
  DCAGRS" is therefore not verifiable in DBLP; the `first_year` of DCAGRS is the first edition
  DBLP has (2001).
- **DCFS gaps.** No 2009 and 2010 in `conf/dcfs`: the 11th and 12th workshops appear in DBLP only
  as CoRR records (`journals/corr/abs-0907-5257` and `abs-1008-1270`, titles "Proceedings
  Eleventh/Twelfth ... DCFS"). No 2024 edition (23rd in 2023, 26th in 2025). Papers of the two
  CoRR volumes are outside the stream; whether to add them is an open point for P1-01.
- **FDSR**: PLAN says DCFS took its name after merging with FDSR. DBLP has no FDSR stream or
  record, so this cannot be confirmed and no FDSR entry was made.
- **DLT** matches the plan (since 1993, LNCS), with details: the first editions (1993, 1995,
  1997, 1999) are biennial and not LNCS (World Scientific, an Aristotle University volume);
  Springer LNCS from 2001. `conf/dlt/2000` is the proceedings of a different meeting (the Kyoto
  colloquium "Words, Languages & Combinatorics III", published 2003) that DBLP files in the DLT
  stream; it is the one edition that is not DLT.
- A proceedings record often carries the volume's DOI in `ee` (for example
  `https://doi.org/10.1007/978-3-030-24886-4` for DLT 2019); this will fill `proceedings_doi`.
- Every edition found in the three streams has a `proceedings` record (31, 30 and 23 editions, counting
  WIA/CIAA and DCAGRS/DCFS together). Editions are also derived from the `crossref` keys of papers
  as a safeguard for streams where a record is missing; nothing needed it here.

### Fixtures

`tests/fixtures/dblp/dblp_sample.xml.gz` holds 20 real DBLP records (the proceedings of
DLT 2019 and 2000, CIAA 2019, WIA'99, DCFS 2019 and DCAGRS 2001, with up to three of their real
papers each, and one article of another stream). `make_sample.py` in the same folder rebuilds it
from the dump; `dblp.dtd` is a copy of the dump's DTD.

## OpenAlex: verified

Method: `GET /sources?search=<name>` (cost kind `search`) for each name and acronym, then
`GET /works?filter=primary_location.source.id:<id>` (cost kind `list`) to see what sits under
each source. API key passed as `api_key` (this works; see `sources.md`).

| Venue | Query that found it | Source ID | Type in OpenAlex | Works under it | Observation |
|---|---|---|---|---|---|
| DLT | "Developments in Language Theory" | S4306418189 | conference | 136 (source record), 159 with this as primary location | Mixed years from 1994; most have no DOI, some are non-FLAT noise (a 2015 energy-saving system paper). |
| CIAA | "Conference on Implementation and Application of Automata" | S4306419526 | conference | 8 (source), 19 as primary location | Only 2002 papers, DOIs `10.5555/...` (ACM DL). The acronym "CIAA" finds nothing. |
| DCFS | "DCFS" | S4306507593 | **journal** | 106 (source), 116 as primary location | Papers from 2001 on, mostly without DOI. |
| DCFS | "Descriptional Complexity of Formal Systems" | S4306418178 | conference | 3, 4 as primary location | Includes one stray "Lecture Notes in Computer Science" volume record. |
| WIA | "Workshop on Implementing Automata", "WIA implementing automata", "Implementing Automata" | none | | | 0 results. |
| DCAGRS | "DCAGRS", "Descriptional Complexity of Automata, Grammars" and variants | none | | | 0 results. |

The LNCS book series is S106296714 ("Lecture notes in computer science", ISSN 0302-9743,
593,340 works). Check of the "LNCS problem" (PLAN §8.4): the DLT 2019 volume DOI is
`10.1007/978-3-030-24886-4` (from the DBLP proceedings record). The work at
`10.1007/978-3-030-24886-4_1`, "Inherent Size Blowup in omega-Automata", lists only the LNCS
series source as its location, while the same title appears under the DLT source **without a
DOI**. So the conference source is a small, partly duplicated subset, and the DOI-bearing record
sits under the series. This supports the plan: DBLP defines venue membership, OpenAlex is joined
by DOI. The LNCS series ID is not added to any venue (it would claim all of LNCS).

Open points for P1-02 (not decided here):
- Whether the near-empty conference sources (CIAA: 8 works) are worth keeping in
  `openalex_source_ids` once DOI joining works; harmless for now.
- OpenAlex lists "DCFS" as a *journal*; `kind` in `venues.yaml` is the Atlas's own and stays
  `conference`.
