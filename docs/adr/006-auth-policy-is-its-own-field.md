# ADR 006 — Authorisation is declared, never inferred from risk class

**Status:** accepted · **Date:** 2026-09-09

## Context

Our first design gated tools with:

```python
needs_authorisation = (tool.visibility == "private") or (tool.risk != "read_only")
```

That rule contradicted our own tool table. `escalate_to_registrar` is `terminal`,
so `risk != "read_only"` was true, so the rule demanded authorisation on a tool
that must never be gated.

It was also wrong in the other direction, and that direction is worse. Deriving
authorisation from risk class implies **read-only means safe to expose**. It does
not. A student's request status is *their* data. Read-only describes what a tool
does to the world, not who may see the answer.

## Decision

Every tool declares **three independent fields** in code:

| Field | Answers | Used by |
|---|---|---|
| `risk` | what this does to the world | logging, loop bounds, review attention |
| `visibility` | whose data it touches | a review invariant |
| `auth_policy` | **who may invoke it** | **the gate, and only this** |

`Session.authorize()` dispatches on `auth_policy` and reads nothing else. No
branch in it mentions `risk`.

```
lookup_service_information   read_only       public    none
check_my_request_status      read_only       private   session_owner
book_advisor_appointment     side_effecting  private   session_owner_fresh
escalate_to_registrar        terminal        public    none
```

`visibility` survives as an invariant, enforced by a test: a private tool may not
declare `auth_policy: none`. That catches the mistake the old rule was trying to
prevent, without letting risk class leak into the gate.

## Why `escalate_to_registrar` is ungated

It creates a hand-off for the current session's own conversation and takes no
subject identifier, so there is nothing to impersonate. Requiring authorisation
to ask for a human would make the failure mode "the student in trouble cannot
reach a person", which is worse than the risk it removes.

## Consequences

`check_my_request_status` is the case that makes the distinction demonstrable
rather than asserted: it is read-only *and* gated, and `tests/test_tool_safety.py`
test 1 shows the same tool succeeding for its owner and being denied for another
student's request.
