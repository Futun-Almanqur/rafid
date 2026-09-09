# ADR 002 — Model choice is a routing table, not a winner

**Status:** accepted · **Date:** 2026-09-09

## Context

"Which model is best?" is the wrong question. The right one is *which model, for
which slice of traffic, at what cost and what latency, under which data
classification.*

## Decision

A routing table in `configs/rafid.yaml`, with four routes over two dialects and
two kinds:

| Route | Kind | Residency | Used for |
|---|---|---|---|
| `primary` | commercial | cloud | the service workflow; anything that must refuse well |
| `cheap` | commercial | cloud | guards, router, and FAQ answering **behind the cascade** |
| `comparison` | commercial | cloud | the second wire dialect |
| `onprem` | **open-weight** | on-premise | residency-pinned traffic; the fallback hop |

Switching any route is two environment variables. No code changes.
`tests/test_architecture.py` fails if that stops being true.

## Evidence

Measured over our own golden set (`BENCHMARKS.md`):

| Route | Kind | Overall | ar | safety | halalas/call |
|---|---|---|---|---|---|
| primary | commercial | 100% | 100% | 100% | 0.4851 |
| cheap | commercial | 96% | 96% | 88% | 0.0226 |
| comparison | commercial | 96% | 96% | 100% | 0.6653 |
| onprem | open-weight | 92% | 92% | 81% | 0.3100 |

The open-weight route loses most on **safety** and on **Arabic**. That is what
shapes the table — not the headline average, which hides both.

## Recommendation

FAQ answering goes to `cheap` **behind the cascade** (see `DECISIONS.md`), the
service workflow stays on `primary`, and anything a data classification pins
on-premise goes to `onprem` with the measured quality cost accepted and written
down.

## The break-even, honestly

Computed from throughput we measured, quoted against **both** commercial tiers
(`BENCHMARKS.md`). It carries a caveat we will not bury: the measurement was
taken against a latency-compressed simulator, so it describes our harness. The
arithmetic is correct in form and must be re-run against a real served model
before anyone acts on it.
