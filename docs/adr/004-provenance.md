# ADR 004 — Provenance: what is borrowed, and what is ours

**Status:** accepted (skeleton — the "Adaptation log" table is filled during phase 1)
**Date:** 2026-09-09
**Decides:** where the local backend comes from, and where the boundary between
borrowed infrastructure and original work is drawn.

---

## Context

The capstone requires a notebook that opens in Colab and reaches a working
conversation with **no API key required by default**. That needs a backend that
answers without credentials.

The course ships one: `murshid/infra/mockgw`, a FastAPI service that speaks both
provider wire dialects and answers from rules rather than weights. The capstone
explicitly permits reuse of this kind:

> "You may read, borrow patterns from, and copy plumbing out of `murshid/` — that
> is what a reference implementation is for."

And it draws the line in the same paragraph:

> "The domain, the tools, the corpora, the golden set and the guards must be
> yours, because every rubric section below is scored on evidence you produced
> about **your** traffic."

## Decision

**Vendor `murshid/infra/mockgw` into this repository as `gateway/`.** Keep its
transport and accounting machinery unchanged. Replace every domain constant with
Wadi University's. Record both halves in this document rather than leaving the
borrowing implicit.

## What is borrowed — infrastructure, credited

| Component | What it provides | Changed? |
|---|---|---|
| Wire contract — `POST /v1/chat/completions` and `POST /v1/messages` | Both dialects, so both of our adapters are exercised against real shapes | no |
| `usage` accounting, including `cached_input_tokens` | Makes the ≥65% prompt-cache requirement measurable rather than asserted | no |
| Prompt-cache model — byte-stable prefix, minimum cacheable length, TTL | A cache that can genuinely miss, which is what makes prefix stability worth proving | no |
| HTTP error taxonomy — 429 with `Retry-After`, 529, 503, 504, 400 | The retry-vs-fallback drills have something real to react to | no |
| Fault injection on a timer, targeted at one model | The drills are reproducible on demand instead of waiting for a bad day | no |
| Streaming frames, `finish_reason` control flow, tool-call plumbing | The bounded tool loop has a real protocol to bound | no |
| Directory-grounded answering | The backend cannot state a fact absent from the directory it was given — which is what makes a golden set mean anything | mechanism kept, **our directory** |
| Tiered degradation profiles | The open-weight tier is deterministically worse, so comparisons are reproducible | retuned only if our slices come out degenerate |

## What is ours — no exceptions

**Domain · service directory · tools · authorisation model · prompts · guard
corpora · golden set · safety tests · evaluation expectations.**

The working rule, checked at every phase boundary:

> If a grader could diff one of our files against `murshid/` and find it
> substantially unchanged, it is in the wrong list. Structure and plumbing may
> rhyme. Content may not.

## Adaptation log — every domain constant replaced

*(Filled in during phase 1, as each edit is made. Listed here now so the edits
are made deliberately rather than discovered later.)*

| In the borrowed code | Reference implementation's value | Ours | Done |
|---|---|---|---|
| Service-type hints | commercial_licence, civil_records, traffic_services, municipal_permits | Wadi campus service taxonomy | ☐ |
| Identifier patterns | Saudi national ID, mobile, IBAN | `WU-STU-\d{6}`, `WU-REQ-\d{6}`, `WU-APT-\d{6}` | ☐ |
| Location list | eight Saudi cities | Wadi University campuses | ☐ |
| Fallback contact | "the service centre (199)" | the Wadi registrar | ☐ |
| Extraction fields | Murshid's citizen ticket | our student request object | ☐ |
| Tool-result payload keys | Murshid's three tools | our four tools | ☐ |
| Canary token | Murshid's | ours | ☐ |
| Service directory | Saudi government services | 12 Wadi campus services | ☐ |

**Note on identifiers.** The reference implementation matches realistic Saudi
national-ID, IBAN and mobile patterns. We do not reproduce those. Every
identifier in this project is unmistakably fictional — `WU-STU-000123`,
`WU-REQ-123456` — which loses nothing: the privacy problem this application
exists to demonstrate is **authenticated-session ownership and cross-student
access**, and that works identically with fictional identifiers.

## Consequences

**Accepted.** Quality numbers produced against this backend are measurements of
a deterministic simulator, not evidence about any model's capability. What they
*do* measure honestly: token accounting, prompt-cache behaviour, guard
effectiveness, grounding, the cost meter, and every gate in the pipeline — which
is what this project is graded on.

This caveat is recorded in the known-limitations section of
`EVALUATION_REPORT.md`, together with what would have to be re-run against a real
provider to change it. Pointing a route at a real provider is two environment
variables and no code change; that substitution being a config edit is the whole
argument for the model boundary, and `tests/test_architecture.py` fails if it
stops being true.

**Also accepted.** Vendoring means we own the maintenance of a copy. For a
four-day capstone with a fixed submission date, that cost is zero.

## Alternatives rejected

| Alternative | Why not |
|---|---|
| Clone the course repository at notebook runtime for its gateway | The notebook would no longer stand alone, and the backend would still answer in the reference implementation's vocabulary — grounding our golden set in someone else's domain |
| Write a backend from scratch | Days of work for no rubric points, and prompt-cache and fault semantics would have to be re-derived rather than inherited |
| Require an API key | Fails the capstone requirement directly: "no key required by default" |

## Related

- ADR 001 — architecture pattern *(phase 3)*
- ADR 002 — model and routing choice, with the break-even *(phase 25)*
