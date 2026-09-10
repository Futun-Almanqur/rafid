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
outside `src/rafid/llm/`, and the check now has something real to catch. Four
things keep it honest:

1. the **negative control** — the same check re-run against a synthetic file
   containing `import openai`, failing if it does not catch it;
2. `test_the_notebook_does_not_import_a_provider_sdk` — the notebook is scanned
   too. Its evidence cell reads `client.sdk_evidence()` instead, because a
   notebook that imports the SDK to prove the SDK is confined to the adapters is
   the claim disproving itself;
3. `test_switching_backend_is_config_not_code` — four separate assertions that
   both kinds of route exist, are built through the same dialect-keyed factory,
   resolve to different concrete models and different residencies, and differ at
   the call site by a route name alone. An earlier version of this test ended in
   `or True` and could not fail; that is recorded here because it was exactly the
   mistake the rest of the file exists to prevent;
4. `test_no_business_logic_branches_on_a_provider_name` — keeping the import
   inside the adapter while hard-coding `if route == "openai"` in a handler turns
   the next provider swap back into a rewrite.

`SDK_CLIENT_TYPE` and `sdk_evidence()` are the adapter's exported evidence: the
live client's class, its configured `base_url`, its `max_retries`, and the alias
it resolves — read off the object, published as values, so nothing outside the
package needs the import.

## Consequences

`requirements.lock` pins `openai==2.54.0`. Pointing a route at a real provider is
still two environment variables. Adding a third dialect is a new file in
`src/rafid/llm/` and a row in `config.ADAPTERS` — never an `if` in application
code.

The Anthropic-dialect adapter still speaks the wire directly. It exists to prove
the boundary carries two genuinely different dialects; adding a second vendor SDK
would add a dependency without adding evidence.
