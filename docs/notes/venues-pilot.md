# Pilot venues: verification notes (P0-03)

Session date: 2026-11-15. All calls went through `flatatlas.http.SourceClient` (cached under
`data/raw/`, rate limited, budget guarded). Entries in `config/venues.yaml` carry
`verified: {dblp, openalex}` dates that match this note.

## Summary

| Venue | DBLP (stream, first year, editions, predecessor) | OpenAlex source IDs |
|---|---|---|
| DLT | **not verified** (see below) | S4306418189 verified |
| CIAA | **not verified** | S4306419526 verified |
| WIA (CIAA predecessor) | **not verified** | none found |
| DCFS | **not verified** | S4306507593 and S4306418178 verified |
| DCAGRS (DCFS predecessor) | **not verified** | none found |

DBLP values in `venues.yaml` (`dblp_stream`, `first_year`, `last_year`, `successor_of`) are
**still from memory** (PLAN §7.1). Nothing may be harvested from DBLP against them until
`verified.dblp` is set. "Done when: the three venues have verified streams, first years and
predecessor links" is therefore **not met** for DBLP; see "Follow-up" below.

## DBLP: blocked

DBLP now puts an Anubis proof-of-work bot challenge in front of its API. A plain request
(`GET /search/venue/api?q=DLT&format=json`, with or without a descriptive User-Agent) returns
**HTTP 202** with an HTML page ("Making sure you're not a bot!") and a `refresh` header to
`/.within.website/x/cmd/anubis/api/pass-challenge`. The same happened on 2026-11-15 for
`dblp.org`, `dblp.uni-trier.de` and `dblp.dagstuhl.de`.

Solving the challenge from a script would be bypassing bot detection, so it was not attempted.
`SourceClient` treats the 202 as an error (`SourceError: HTTP 202 for ...`), which is the right
outcome. No DBLP response was cached, and so there are no trimmed DBLP fixtures in
`tests/fixtures/dblp/` (the prompt asked for them).

Decision taken with Guilherme in the session: finish the rest of P0-03 and leave the DBLP part
for a follow-up once access works.

### Follow-up (needs a decision outside this session)

Options, in the order they look practical:
1. Ask DBLP (dblp@dagstuhl.de) whether an identified polite client can be allow-listed.
2. Use the DBLP XML dump (`dblp.xml.gz` plus `dblp.dtd`), downloaded by Guilherme in a browser.
   It gives stream keys, editions (proceedings records) and all papers, and is how a full
   harvest at scale would work anyway. Needs a P1-01 design change (parse a local file, not
   API pages) and an entry in DECISIONS.
3. Verify the values by hand on dblp.org in a browser and type the results into `venues.yaml`.

What to check, per venue: stream key (`conf/dlt`, `conf/ciaa`, `conf/wia`, `conf/dcfs`,
`conf/dcagrs`), earliest year, list of editions, and which workshops DBLP records as
predecessors (DCFS and FDSR; WIA and CIAA).

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
593,340 works). Check of the "LNCS problem" (PLAN §8.4): the work "Inherent Size Blowup in
omega-Automata" (2019) appears under the DLT source **without a DOI**, while the work found by
DOI `10.1007/978-3-030-24886-4_1` has exactly that title and lists only the LNCS series source as
its location. So the conference source is a small, partly duplicated subset, and the DOI-bearing
record sits under the series. This supports the plan: DBLP defines venue membership, OpenAlex is
joined by DOI. The LNCS series ID is not added to any venue (it would claim all of LNCS); it is
mentioned in the `notes` of the entries.

Open points for P1-02 (not decided here):
- Whether the near-empty conference sources (CIAA: 8 works) are worth keeping in
  `openalex_source_ids` once DOI joining works; harmless for now.
- OpenAlex lists "DCFS" as a *journal*; `kind` in `venues.yaml` is the Atlas's own and stays
  `conference`.

## Facts that PLAN §7.1 says and this session could not confirm or refute

All of §7.1 for DLT, CIAA, DCFS (first years, WIA 1996 to 1999, DCAGRS since about 1999) is
unchanged: no DBLP access, so no correction was made. PLAN §7.1 was not edited.
