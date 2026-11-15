# P3-00 — Request the university server (Guilherme)

Not a model session. Send the request **at the start of Phase 2** (or earlier): approval usually takes longer than building.

Before sending, replace the estimates with the measured numbers from the G2 review if you have them (bytes per work, harvest duration).

## Request text (adapt)

> **Subject: Virtual server for an open research-data project (The FLAT Atlas)**
>
> I maintain The FLAT Atlas, an open, non-commercial map of the research literature in formal languages and automata theory (topics, papers, authors, venues), built only from open metadata sources (DBLP, OpenAlex, Semantic Scholar, Crossref). The code is public on GitHub and the data will be published with a DOI.
>
> I would like a Linux virtual machine to (1) run the data pipeline on a weekly schedule and (2) host the public website and its read-only API.
>
> **Resources**
> - 8 CPU cores (4 minimum)
> - 32 GB RAM (16 GB minimum)
> - 500 GB SSD storage (200 GB minimum)
> - No GPU required (a small GPU would be welcome but is optional)
> - Ubuntu LTS or Debian, with Docker and Docker Compose; SSH access for me; sudo or membership of the docker group
>
> **Network**
> - Outbound HTTPS to the public internet (API calls to the sources, container registry)
> - Inbound ports 80 and 443 from the internet, and a hostname such as `flat-atlas.<domain>`
> - Expected traffic: low (a research community of a few thousand people)
>
> **Operations**
> - A daily snapshot or a backup location for about 50 GB
> - I administer the software myself; everything runs in containers
> - No personal data beyond public bibliographic metadata; an optional contact field in a correction form
>
> **Duration:** open-ended research infrastructure; I am happy to review yearly.

## When granted, collect
- [ ] Hostname and public DNS name; who manages DNS
- [ ] SSH access method (VPN? jump host? key registration)
- [ ] OS and version; CPU, RAM, disk actually given; where large data should live (mount point)
- [ ] Is Docker allowed? rootless? Is outbound access proxied?
- [ ] Firewall: are 80/443 open from outside the university? If not, what is the process?
- [ ] Backup or snapshot policy; maintenance windows
- [ ] Any university rules for public websites (imprint, privacy notice, accessibility statement)

Write the answers in `docs/notes/server.md` (no passwords). They are the input for session P3-05.

## If the answer is no or slow
See `RISKS.md` R7: the static site keeps working; Phase 2 and P3-01 to P3-04 need no server; P5-01 to P5-03 have static variants.
