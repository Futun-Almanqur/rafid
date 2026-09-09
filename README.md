# Rafid (رافد) — a bilingual student-services assistant

**Author: Futun Hussain Almanqur**

**Programme:** SDA-AIE-213 — Large Language Model Application Engineering
(هندسة تطبيقات النماذج اللغوية الكبيرة), SDAIA Academy
**Cohort dates:** ⟨PENDING-U3⟩
**SDAIA Academy on GitHub:** https://github.com/SDAIAAcademy

**Capstone track: B — Campus services.**
**Extension: none selected.** An extension is only attempted if the mandatory
scope scores ≥ 80 when it is assessed at the end of the build; the capstone is
explicit that "an extension is not a way to buy back a weak section."

---

## What this is

Rafid is a bilingual (Arabic-majority) student-services assistant for **Wadi
University** (جامعة الوادي), a fictional Saudi university. It answers questions
about campus services — transcripts, enrolment letters, fees, withdrawals,
graduation clearance — grounded strictly in a service directory, and it refuses
rather than guessing when a fact is not in that directory.

It does three things a chat wrapper does not:

- **It is grounded.** Answers are composed from a service directory. A fee that
  is not in the directory cannot appear in an answer.
- **It acts, under authorisation.** Four tools spanning three risk classes. The
  side-effecting one — booking an advisor appointment — passes an authorisation
  gate that reads the *authenticated session*, never the conversation. So does
  the private read-only one: **read-only does not mean unauthenticated.**
- **It refuses.** A layered input wall and an outbound wall, both bilingual,
  measured on two numbers that are always reported together: how much of an
  attack corpus is blocked, and how much of a legitimate corpus is blocked by
  mistake.

Every one of those claims has a cell behind it in the notebook.

---

## How to open and run it

**The notebook is the submission.** It runs in Google Colab with no API key
required by default, no manual clone, and no local installation.

1. Open `notebook/capstone.ipynb` in Colab.
2. **Runtime → Run all.**

The first cell does the setup itself: it clones this repository, installs its
pinned dependencies, and starts a local backend on a free port. That clone is
performed by the notebook, not by you — the requirement is zero *manual* setup,
and the setup cell is what delivers it. Nothing else is required. If a stranger
opens the notebook link and hits Run all, they reach a working bilingual
conversation — that is the reproducibility proof, and there is no CI pipeline
standing in for it.

### Running it locally instead

```bash
git clone <this repository> && cd rafid
python -m venv .venv && .venv/bin/pip install -r requirements.lock
.venv/bin/python -m gateway.app.main          # the local backend
.venv/bin/pytest                              # the test suite
```

---

## Repository layout

```
notebook/capstone.ipynb   the submission: every discipline demonstrated as a run cell
src/rafid/
  llm/                    the model boundary — interfaces, adapters, retry + fallback
  prompts/                versioned prompt artefacts, loaded by id and version
  guards/                 the input wall and the outbound wall
  domain/                 the service directory, the request contract, the session
  tools/                  four tools, three risk classes, declared auth policies
  pipeline/               the five stages, plus the bounded tool loop
  caching/                exact and semantic response caching
  observability/          structured logging and the cost meter
gateway/                  the local backend (see docs/adr/004 for its provenance)
eval/                     the golden set, the harness, the gate, judge calibration
data/                     corpora: questions, attacks, legitimate traps, near-misses
scripts/                  every measurement this project takes
docs/adr/                 architecture decision records
tests/                    architecture rules, stage isolation, tool safety
```

---

## The evidence

| Document | What it holds |
|---|---|
| `EVALUATION_REPORT.md` | Overall and sliced results for both backends, judge calibration, safety suite status, and known limitations |
| `BENCHMARKS.md` | Every measured number, with the command that produced it |
| `DECISIONS.md` | The ADR index, the routing recommendation with its break-even, and one trade-off reversed |

*(These are produced during the build. This README is the phase-0 stub.)*

---

## Status

**Phase 0 of 28 complete** — repository skeleton, `.gitignore`, this README, and
ADR 004 (provenance). No application code has been written yet.

Items marked `⟨PENDING-U3⟩` above must be resolved before submission; a check
for that marker is part of the final read-through.
