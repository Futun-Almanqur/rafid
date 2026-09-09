# ADR 005 — Adapters speak the wire, not the vendor SDK

**Status:** accepted · **Date:** 2026-09-09

## Context

The model boundary requires provider-specific code to live in one place. The
usual way is to import the vendor SDK there.

## Decision

The adapters in `src/rafid/llm/` speak the HTTP wire contract with `httpx`. No
vendor SDK is imported anywhere in this project.

## Why

The SDK provides retries, typed models and error taxonomy. We already have all
three above the boundary — `ResilientClient`, our pydantic types, `LLMError` —
and having two of each is worse than having one. The SDK surface also changes
between minor versions; the wire contract does not.

## The honest objection, and the answer

If we never import a provider SDK, does "no provider SDK outside the adapters"
mean anything? On its own it would be vacuously true.

So `tests/test_architecture.py` carries a **negative control**: the same check is
re-run against a synthetic file containing `import openai`, and the test fails if
the check does not catch it. There are three such controls, one per architecture
rule. A check that cannot fail is decoration, and "presence is not effect"
applies to tests too.

## Consequences

Pointing a route at a real provider is still two environment variables. Adding a
third dialect is a new file in `src/rafid/llm/` and a row in `config.ADAPTERS` —
never an `if` in application code.
