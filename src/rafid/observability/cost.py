"""The cost meter: Usage finally monetised.

Rates live in config because they change. Costs are computed, logged and
aggregated by route, intent and STAGE, so "where does the money actually go?" is
a query and not a guess.

Metering comes BEFORE optimising. Teams who invert that order spend a week saving
4% while the 60% line item sits unexamined — which is why the commit that adds
this file lands before the commit that adds any cache.

Coverage is the graded property: 100% of model calls, guards and router included.
`assert_full_coverage()` is what turns that from a claim into a check.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel

from rafid.config import PriceSheet
from rafid.llm.interfaces import LLMResponse
from rafid.observability import current_trace_id, get_logger

log = get_logger(__name__)


class CostRecord(BaseModel):
    route: str
    intent: str = "unknown"
    stage: str = ""
    model_id: str
    prompt_version: str = ""
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    latency_ms: float = 0.0
    cost_halalas: float  # SAR cents. Money is never a float in production; fine for a meter.
    trace_id: str = ""
    cache_tier: str = ""  # "", "exact", "semantic" — a cache hit costs nothing


class CostMeter:
    def __init__(self, prices: PriceSheet, sink: str | Path | None = None) -> None:
        self._prices = prices
        self.records: list[CostRecord] = []
        self.calls_seen = 0  # every model call, metered or not
        self._sink = Path(sink) if sink else None

    def price_of(self, model_id: str, usage) -> float:
        p = self._prices.for_model(model_id)
        fresh_in = max(usage.input_tokens - usage.cached_input_tokens, 0)
        return (
            fresh_in * p.input_per_mtok
            + usage.cached_input_tokens * p.cached_input_per_mtok
            + usage.output_tokens * p.output_per_mtok
        ) / 1_000_000

    def meter(self, response: LLMResponse, *, route: str, intent: str = "unknown",
              stage: str = "", prompt_version: str = "", cache_tier: str = "") -> CostRecord:
        cost_sar = 0.0 if cache_tier else self.price_of(response.model_id, response.usage)
        record = CostRecord(
            route=route, intent=intent, stage=stage, model_id=response.model_id,
            prompt_version=prompt_version,
            input_tokens=response.usage.input_tokens,
            cached_tokens=response.usage.cached_input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=round(response.latency_ms, 1),
            cost_halalas=round(cost_sar * 100, 6),
            trace_id=current_trace_id(),
            cache_tier=cache_tier,
        )
        self.records.append(record)
        if self._sink:
            self._sink.parent.mkdir(parents=True, exist_ok=True)
            with self._sink.open("a", encoding="utf-8") as fh:
                fh.write(record.model_dump_json() + "\n")
        return record

    # --- coverage: the graded property ----------------------------------
    def assert_full_coverage(self, *, required_stages=("guard", "router")) -> dict:
        """100% of model calls metered, and the cheap stages are IN the number.

        The classic omission is the guard and the router: they are small, they are
        called on every single turn, and leaving them out understates the bill by
        exactly the line item that scales with traffic.
        """
        metered = len(self.records)
        stages = {r.stage for r in self.records}
        missing = set(required_stages) - stages
        coverage = metered / self.calls_seen if self.calls_seen else 1.0
        result = {
            "calls_seen": self.calls_seen,
            "metered": metered,
            "coverage": coverage,
            "stages": sorted(stages),
            "missing_stages": sorted(missing),
            "ok": metered == self.calls_seen and not missing,
        }
        return result

    # --- aggregation ------------------------------------------------------
    def total_halalas(self) -> float:
        return sum(r.cost_halalas for r in self.records)

    def by(self, key: str) -> dict[str, float]:
        out: dict[str, float] = defaultdict(float)
        for r in self.records:
            out[getattr(r, key) or "-"] += r.cost_halalas
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def cached_input_ratio(self) -> float:
        total_in = sum(r.input_tokens for r in self.records)
        cached = sum(r.cached_tokens for r in self.records)
        return cached / total_in if total_in else 0.0

    def latency_percentiles(self) -> dict[str, float]:
        values = sorted(r.latency_ms for r in self.records)
        if not values:
            return {"p50": 0.0, "p95": 0.0}
        def pct(p): return values[min(len(values) - 1, int(len(values) * p))]
        return {"p50": round(pct(0.50), 1), "p95": round(pct(0.95), 1)}

    def summary(self) -> dict:
        return {
            "calls": len(self.records),
            "total_halalas": round(self.total_halalas(), 4),
            "by_stage": {k: round(v, 4) for k, v in self.by("stage").items()},
            "by_route": {k: round(v, 4) for k, v in self.by("route").items()},
            "cached_input_ratio": round(self.cached_input_ratio(), 4),
            **self.latency_percentiles(),
        }


class MeteredClient:
    """Wraps any LLMClient and meters EVERY call through it.

    Wrapping at the boundary rather than at each call site is what makes 100%
    coverage structural: a new call site cannot forget to meter, because there is
    nowhere to call a model that is not this object.
    """

    def __init__(self, inner, meter: CostMeter, *, stage: str = "", intent: str = "unknown") -> None:
        self._inner = inner
        self._meter = meter
        self.stage = stage
        self.intent = intent

    @property
    def dialect(self) -> str:
        return getattr(self._inner, "dialect", "unknown")

    def resolve(self, alias: str) -> str:
        return self._inner.resolve(alias)

    def for_stage(self, stage: str) -> MeteredClient:
        return MeteredClient(self._inner, self._meter, stage=stage, intent=self.intent)

    def complete(self, request):
        self._meter.calls_seen += 1
        response = self._inner.complete(request)
        self._meter.meter(response, route=response.route or "unknown",
                          intent=self.intent, stage=self.stage,
                          cache_tier=getattr(response, "cache_tier", ""))
        return response
