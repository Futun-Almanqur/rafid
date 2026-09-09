# ADR 001 — Router-first, with exactly one bounded tool loop

**Status:** accepted · **Date:** 2026-09-09

## Context

Rafid has three kinds of turn: a question the service directory answers, a
request that touches the student's own record, and a conversation that belongs
with a human. They have very different costs and very different risks.

## Decision

**Router-first.** One cheap classification call decides the destination, then the
turn takes the cheapest path that can serve it:

```
guard_input | route_intent | (service_info | workflow | escalate) | guard_output
```

`service_info` is a single grounded call with no tools. `workflow` is the only
path with tools, and it runs **one** bounded loop (4 iterations). `escalate`
makes no model call at all — humans are not a model call.

## Alternatives rejected

| Alternative | Why not |
|---|---|
| One agent with all tools available on every turn | Every FAQ turn pays for tool schemas in the prompt and risks a tool firing on a question. The router costs one small call and removes both. |
| A chain of specialised agents | More moving parts than the domain has. Five named stages that each run alone in a test is the ceiling of what we can debug. |
| No router; let the model decide | The decision then lives in a prompt, unversioned and unmeasurable. Routing accuracy is a slice in the golden set precisely because it is a component with its own failure rate. |

## Consequences

The router is a component with its own cost, its own prompt version and its own
slice in the evaluation. Its deliberate fallback is `service_info` — the cheap,
read-only, grounded path — because guessing towards the path that can *act* is
the expensive mistake.

Every stage is individually testable (`tests/`), which is the rule that keeps the
decomposition honest: if a stage cannot be run alone in a test, it is not a stage.
