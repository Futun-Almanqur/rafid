# Decisions

The architecture decision records live in [`docs/adr/`](docs/adr/). This page is
the index, plus the section a review board always asks for and most projects
cannot answer: what did we change our mind about?

| ADR | Decision | Status |
|---|---|---|
| [001](docs/adr/001-architecture-pattern.md) | Router-first, with exactly one bounded tool loop | accepted |
| [002](docs/adr/002-model-and-routing.md) | Model choice is a routing table, not a winner | accepted |
| [004](docs/adr/004-provenance.md) | The local backend is vendored, and what is borrowed is itemised | accepted |
| [005](docs/adr/005-adapters-over-sdks.md) | The adapter calls the provider SDK, and only the adapter | accepted (reversed once) |
| [006](docs/adr/006-auth-policy-is-its-own-field.md) | Authorisation is declared, never inferred from risk class | accepted |

---

## Trade-offs we reversed

### The routing table, reversed once and then re-shaped

**First decision.** Send the answering traffic to the small model. The arithmetic
was overwhelming: 96.7% off the bill for the 200-turn replay, from 65.42 halalas
to 2.18.

**What happened.** The regression gate blocked it. Not on the average, which
looked survivable at 95.8%, but on the slices: `risk=safety` fell to 88%,
`language=ar` fell 4 points and `language=en` fell 5. Every failing case was an
out-of-directory question where the small model stopped saying "I don't know" and
started producing a plausible fee.

**What we did not do.** Move the traffic back to the flagship and hand back the
saving. That is the reflex, and it treats the gate as an obstacle rather than as
information. The gate had told us something specific and useful: *the small model
is fine except when it should be refusing.*

**Second decision.** A cascade. The small model answers; if the answer contains a
monetary amount that is not in the service directory, the request is re-asked on
the flagship. The escalation signal is
`rafid.domain.directory.unsupported_amounts` — **the same deterministic check the
gate failed on**, which means the cascade escalates on exactly the condition that
would have blocked the change.

**Result.** The suite returned to 100% on every slice, safety at 100%, and the
cost landed at 2.03 halalas — because on this traffic the cascade escalated
**0 of 84 calls**. Its insurance premium was nothing, and that is the reason the
routing change shipped at all.

Evidence: `BENCHMARKS.md` §"Module 6 — before / after", and
`eval/out/benchmarks.json`.

---

### Masking every identifier, reversed on the first end-to-end run

**First decision.** Mask every Wadi identifier inbound — student ids, emails,
request references, appointment numbers — before any model or log sees them. It
looked like the strictly safer choice.

**What happened.** The status lookup stopped working. A student asking "where has
WU-REQ-100045 got to?" had their reference replaced with `⟦REQUEST_REF_1⟧` before
the model saw it, so the model could not pass it to the tool. The feature was
disabled by its own protection.

**What we noticed.** A request reference identifies a *case*, not a person. It is
opaque, it carries nothing about the student, and masking it protected nobody —
while the thing that actually protects it, ownership checked at the gate against
the authenticated session, was unchanged either way.

**Second decision.** Split the patterns. PII (student id, email) is masked
inbound and may never appear in a reply. A case reference is left readable, and
the outbound wall blocks one only when the session does not own it — so a student
sees their own confirmation number and never sees anyone else's.

**Result.** The lookup works, the cross-student refusal still fires (test 1 in
`tests/test_tool_safety.py`), and the protection sits where the real control is.
Masking would have looked safer and been worse.

---

### Speaking the wire instead of the SDK, reversed

**First decision.** Adapters would use `httpx` and not import a vendor SDK: we
already had retries, typed models and an error taxonomy above the boundary, and
the SDK surface churns while the wire does not.

**What was wrong with it.** "No provider SDK outside the adapters" is nearly
unfalsifiable when there is no provider SDK anywhere in the project. We shored it
up with a negative control, which was the right instinct — but the boundary is
only interesting if something real sits on the far side of it.

**Second decision.** The OpenAI-dialect adapter now builds an `openai.OpenAI`
client from the configured `base_url` and calls `chat.completions.create`. Retry
and fallback stay in `ResilientClient` (`max_retries=0` on the SDK — two retry
layers turn one 429 into six), aliases stay in config, and
`openai.APIStatusError` is caught in the adapter and normalised to `LLMError` so
nothing above the boundary ever catches an SDK type.

**Result.** Both fault drills still pass through SDK-raised exceptions, with
`Retry-After` honoured and the fallback hop intact. The architecture test now has
something real to police. See ADR 005.

---

## Two bugs our own runs found

Recorded because the runs that found them are the point.

**An Arabic normalisation mismatch.** The golden set's first full run scored
97.9% and named one failure: an Arabic escalation that did not route. Our input
guard folds Arabic orthography (ى → ي, ة → ه) before anything downstream sees the
text — which is what catches the homoglyph attacks — but the routing vocabulary
downstream held the *unfolded* spelling, so `شكوى` silently stopped matching.
Normalisation before matching only works if both sides are folded. Fixed in the
pipeline; the expectation was never touched.

**A cache threshold validated against the wrong problem.** The first threshold
sweep compared each near-miss question only against its own pair and reported
zero wrong hits at 0.80. The live cache then found one: `nm06` collided with
`nm01`, which an earlier iteration had already cached. A real cache compares a
question against everything it holds. The sweep now runs the live cache, and the
chosen threshold moved to 0.85.
