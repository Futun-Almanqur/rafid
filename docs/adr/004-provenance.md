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

Completed in phase 1. Every replacement below was applied by
`scripts/_phase1_adapt.py`, which asserts a match count for each edit and writes
nothing if any edit fails — so an edit that silently matched nothing is a build
failure rather than a leftover. The script is committed alongside the result, so
the adaptation is reviewable as a diff.

### Planned rows

| # | In the borrowed code | Reference implementation's value | Ours | Hits | Done |
|---|---|---|---|---|---|
| 1 | Service-type hints and the enum guard | `commercial_licence`, `civil_records`, `traffic_services`, `municipal_permits` | `records`, `enrolment`, `finance`, `campus_services` | 2 | ☑ |
| 2 | Identifier patterns | `\b[12]\d{9}\b` (national ID), `(?:\+?966\|0)5\d{8}\b` (mobile), `\b[A-Z]{2}\d{8}\b` (reference) | `WU-STU-\d{6}`, `WU-STU-\d{6}@students.wadi.example`, `WU-REQ-\d{6}` | 1 | ☑ |
| 3 | Location list and its detector | eight Saudi cities, `detect_city` | four Wadi campuses (Main, North, Medical, Online), `detect_campus` | 5 | ☑ |
| 4 | Fallback contact | `service_centre:` → "the service centre (199)" | `registrar_contact:` → "Admissions & Registration" / "قبول وتسجيل" | 3 | ☑ |
| 5 | Extraction fields | `applicant.national_id`, `applicant.phone`, `city`, "Citizen asks about…" | `student.student_id`, `student.email`, `campus`, "Student asks about…" | 5 | ☑ |
| 6 | Tool names the simulator answers to | `check_application_status`, `book_appointment`, `escalate_to_agent` | `check_my_request_status`, `book_advisor_appointment`, `escalate_to_registrar` | 7 | ☑ |
| 7 | Canary token | Murshid's `⟦MRSHD-7f3a⟧` | — | — | **N/A — not in the gateway** |
| 8 | Service directory | Saudi government services | 12 Wadi campus services in `data/service_directory.yaml` | — | ☑ |

**Row 7, corrected.** The canary is not a gateway constant. It lives in the
application's prompt registry, which does not exist yet. **Deferred to phase 7**,
where our own canary is defined with the prompt artefacts. Listing it here in the
phase-0 skeleton was an error in the plan, not a missed edit.

### Rows discovered during phase 1

Not in the original list. Found by reading the vendored code rather than by
planning it, which is the reason the log is a working document.

| # | In the borrowed code | Reference implementation's value | Ours | Hits | Done |
|---|---|---|---|---|---|
| 9 | Open-weight model tier name | `murshid-onprem` | `wadi-onprem` | 8 | ☑ |
| 10 | Untrusted-content prompt tag | `<citizen_message>` | `<student_message>` | 6 | ☑ |
| 11 | Booking-argument key | `city` | `campus` | 4 | ☑ |
| 12 | Reference-format hint shown to the student | "two letters and eight digits, e.g. CR12345678" | "It looks like WU-REQ-123456" | 1 | ☑ |
| 13 | Off-directory invented fees | SAR 150 / 250 / 75 | SAR 310 / 145 / 890 — chosen so that none appears anywhere in our directory | 1 | ☑ |
| 14 | Schema-failure injection values | `Al Khobar`, a malformed national ID | `South` (not in our campus enum), `WU-STU-12` (malformed) | 1 | ☑ |
| 15 | Repair-loop comment referring to the citizen | prose | prose | 1 | ☑ |

### The sweep

`scripts/_phase1_adapt.py` refuses to write unless the adapted files contain **no
occurrence** of `murshid`, `citizen`, `national_id` or `iban`, case-insensitive.
That check passed:

```
sweep clean: no 'murshid', 'citizen', 'national_id' or 'iban' remains
wrote 2 files
```

### What was deliberately NOT changed

The vendored files keep their original module layout and import style
(`from app import brain`) so they stay diffable against their source.
`scripts/run_gateway.py` puts `gateway/` on `sys.path` instead, which keeps the
adaptation confined to domain constants.

The model tier names `course-flagship`, `course-small` and `course-anthropic` are
kept. They name the *simulator's* tiers, not our domain, and keeping them makes
the borrowed behaviour traceable to its source. Only `murshid-onprem` was renamed,
because it carried the reference implementation's name.

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

## Known issue found in phase 1 — the tokenizer needs the network on first run

The gateway counts tokens with `tiktoken`, which downloads its BPE table
(`o200k_base`) from `openaipublic.blob.core.windows.net` the first time it is
imported. That download is **blocked in the sandbox this repository was built in**,
so the gateway cannot start as a server there at all:

```
requests.exceptions.ProxyError: HTTPSConnectionPool(
  host='openaipublic.blob.core.windows.net', port=443): ...
  Tunnel connection failed: 403 Forbidden
```

Colab has open network, so the first run there fetches it normally and this does
not threaten the zero-setup requirement. Two consequences are carried forward:

1. **Phase 2 must confirm it** — the Colab setup cell is the first place the
   gateway starts over a real socket, and the download must be observed to
   succeed there. Until then, treat this as unproven on the target platform.

   **Status after phase 2: STILL OPEN.** Not resolved, and not disproved — the
   test has not been run. The phase-2 setup cell was written and now raises
   rather than substituting an approximation, but it could not be executed:
   the build sandbox has no access to Colab (`colab.research.google.com`
   returns 000) and the BPE host is still denied there. The evidence that
   closes this issue can only come from a Colab run, and the setup cell prints
   `TOKENIZER=REAL` with the encoding name precisely so that run produces it.
2. The phase-1 verification (`scripts/verify_gateway.py`) installs an approximate
   byte-level encoder **inside the script only** so the rest of the checks could
   run. The token counts in its captured output are therefore not tiktoken's.
   Nothing else in that output depends on them.

## Related

- ADR 001 — architecture pattern *(phase 3)*
- ADR 002 — model and routing choice, with the break-even *(phase 25)*
