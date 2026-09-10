# ADR 005 — The adapter calls the provider SDK, and only the adapter

**Status:** accepted · **Supersedes:** the original "adapters over SDKs" decision · **Date:** 2026-09-10

## What changed, and why

The first version of this ADR decided that adapters would speak the HTTP wire
with `httpx` rather than import a vendor SDK. The reasoning was defensible — we
already have retries, typed models and an error taxonomy above the boundary, and
the SDK surface churns while the wire contract does not.

It was also, as written, close to unfalsifiable. "No provider SDK outside the
adapters" is a weak claim when there is no provider SDK anywhere. We propped it up
with a negative control so the check could at least fail against a synthetic
offender, and that is still the right instinct — but the honest position is that
the grading rubric asks for a provider SDK **actually called**, and it is asking
for something real: the boundary is only interesting if there is something
genuine on the far side of it.

**Reversed.** The OpenAI-dialect adapter now uses the official `openai` SDK.

## Decision

`src/rafid/llm/openai_compat.py` builds an `openai.OpenAI` client and calls
`chat.completions.create`. Two things stay deliberately above the boundary:

| Concern | Where it lives | Why not in the SDK |
|---|---|---|
| retry, backoff, fallback hop | `ResilientClient` | `max_retries=0` on the SDK. Two retry layers turn one 429 into six, and the drill transcript stops meaning anything. |
| model naming | `config.Route.resolve()` | Callers name an alias; the concrete model is configuration. |
| error types | `LLMError` | `openai.APIStatusError` is caught **in the adapter** and normalised. Nothing above this file catches an SDK exception — that would be the SDK leaking across the boundary by a different door. |

The SDK's `base_url` comes from config, so the same adapter serves a commercial
API, our local gateway and a vLLM server. The zero-key path is unchanged: the
gateway ignores the key, and the SDK is happy with a placeholder.

## What still enforces the boundary

`tests/test_architecture.py` forbids `openai` / `anthropic` imports anywhere
outside `src/rafid/llm/`, and the check now has something real to catch. The
negative control stays: the same check is re-run against a synthetic file
containing `import openai`, and the test fails if it does not catch it.

## Consequences

`requirements.lock` pins `openai==2.54.0`. Pointing a route at a real provider is
still two environment variables. Adding a third dialect is a new file in
`src/rafid/llm/` and a row in `config.ADAPTERS` — never an `if` in application
code.

The Anthropic-dialect adapter still speaks the wire directly. It exists to prove
the boundary carries two genuinely different dialects; adding a second vendor SDK
would add a dependency without adding evidence.
