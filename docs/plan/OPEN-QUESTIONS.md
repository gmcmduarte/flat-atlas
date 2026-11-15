# Open questions for Guilherme

Short list. Write your answer under each question. None blocks Phase 0; the "needed by" column says when each starts to matter.

| # | Question | Default if you do not answer | Needed by |
|---|---|---|---|
| Q1 | **Which Claude plan do you have, and how much Fable usage does it allow?** | Workflow as written: Fable for 5 sessions + 6 gates. If Fable is scarce: gates with Sonnet at high effort, Fable only for P1-06 and G1. | P0-00 |
| Q2 | **GitHub account/organisation for the repo** (decides the site URL `https://<name>.github.io/flat-atlas/`), and do you want a custom domain later? | Your personal account; no custom domain. | P0-00 |
| Q3 | **Tier of the broad "core" journals.** I propose that Information and Computation, Acta Informatica, Fundamenta Informaticae and Natural Computing are filtered by the scope rule (Tier B, lenient) and not included wholesale. Agree? | Tier B (decision D-07). | P2-01 |
| Q4 | **Showing abstracts.** Default is never to show or redistribute abstracts. OpenAlex provides many as CC0 data; would you want to *display* those (not redistribute) on paper pages? | No abstracts shown; links only. | P1-10 |
| Q5 | **Proposed venue additions** (PLAN §7.2): strike any you do not want, add any I missed. In particular: Acta Cybernetica as Tier A or B? DNA conference as A or B? | Additions as listed; Acta Cybernetica Tier B; DNA Tier B. | P2-01 |
| Q6 | **Contact email** exposed to the sources (Crossref `mailto`, User-Agent) and shown on the site for corrections. A university address is preferable to a private one. | None chosen; P0-00 asks you. | P0-00 |
| Q7 | **University constraints.** Does your university require an imprint, privacy notice or accessibility statement for hosted sites, and is there a data-protection officer to consult about author profiles (RISKS R12)? | Assume yes; ask before P3-05. | P3-05 |
| Q8 | **Your time.** Roughly how many hours per week? At about 4 hours per week, expect Phase 0–1 in 2–3 months and the full roadmap in 12–15 months. | 4 hours per week. | planning only |
| Q9 | **Languages.** Should non-English works (French, German, Russian classics) be included when the sources have them? | Yes: include, tag by citations and translated-title matches where available; no translation effort. | P6-01 |

## Answers (Guilherme, 2026-11-15)

| # | Answer | Effect |
|---|---|---|
| Q1 | No Fable any more. Only Sonnet 5.5 and Opus 5.5 will be used. | Opus takes the sessions and gates planned for Fable (D-35, supersedes part of D-31). |
| Q2 | Own GitHub account for now (`gmcmduarte`); custom domain later. | Site URL `https://gmcmduarte.github.io/flat-atlas/` until a domain is chosen. |
| Q3 | Do not filter these journals up front. Consider all their publications, then drop the ones that turn out not to belong to FLAT after tagging. | D-36, supersedes D-07. Design in P2-01 / P2-02. |
| Q4 | Show abstracts wherever there is no legal issue. | D-37, supersedes part of D-14. Design in P1-10. |
| Q5 | Start with the venues as listed; more can be added later. | Defaults stand (Acta Cybernetica Tier B, DNA Tier B). |
| Q6 | `guilherme.duarte@fc.up.pt` | Goes in `.env` as `CONTACT_EMAIL`; shown on the site for corrections. |
| Q7 | No university constraints right now. | Ask again before P3-05. |
| Q8 | No timeline; work happens whenever there is time. | Planning only. |
| Q9 | Yes, include non-English works. | Default stands. |

## Things I could not verify (details in PLAN §17)
CORE/ICORE ranks per venue (the portal blocked automated access); venue founding years and predecessor chains (from memory, to be checked against DBLP in P0-03 and P2-01); a few API parameters (OpenAlex per-second limit and DOI batch size, Semantic Scholar batch size); zbMATH Open payload contents; ACM CCS reuse terms; exact Fable usage limits on your plan.
