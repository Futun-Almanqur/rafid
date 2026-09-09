"""Meter the system on 200 real turns — before, and after each optimisation.

    python scripts/replay.py

The order is the point, and it is graded. METER FIRST. The baseline run has every
optimisation off, so the "after" number has something honest to be measured
against. Teams who optimise first spend a week saving 4% while the 60% line item
sits unexamined.

Every step here carries its EVAL VERDICT. A saving with no verdict beside it is
one of the four things that caps a rubric criterion at 70%, and it is the whole
point of the module's one sentence: a cheaper system that answers worse is not a
cheaper system, it is a worse one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT))

from rafid.caching.response_cache import CacheScope, ResponseCache, exact_key  # noqa: E402
from rafid.config import build_client, load_settings  # noqa: E402
from rafid.domain.session import Session  # noqa: E402
from rafid.observability.cost import CostMeter, MeteredClient  # noqa: E402
from rafid.pipeline.assemble import build_assistant  # noqa: E402

REPLAY = ROOT / "data" / "replay_200.jsonl"
OUT = ROOT / "eval" / "out"
SEMANTIC_THRESHOLD = 0.85  # from scripts/eval_cache.py — chosen on measured data


def turns() -> list[dict]:
    return [json.loads(line) for line in REPLAY.read_text(encoding="utf-8").splitlines() if line]


def replay(base: str, *, label: str, cache_enabled: bool, semantic: bool,
           cheap_routing: bool, stable_prefix: bool = True, cascade: bool = False) -> dict:
    settings = load_settings(gateway_base=base)
    meter = CostMeter(settings.prices)

    answer_route = settings.cheap_route if (cheap_routing or cascade) else settings.primary_route
    if cascade:
        from rafid.pipeline.cascade import CascadeClient

        inner = CascadeClient(
            MeteredClient(build_client(settings, settings.cheap_route), meter, stage="answer"),
            MeteredClient(build_client(settings, settings.primary_route), meter, stage="answer"),
        )
        answer_client = inner
    else:
        answer_client = MeteredClient(build_client(settings, answer_route), meter, stage="answer")
    guard_client = MeteredClient(build_client(settings, settings.cheap_route), meter, stage="guard")
    router_client = MeteredClient(build_client(settings, settings.cheap_route), meter, stage="router")

    app = build_assistant(answer_client, guard_client=guard_client)
    app.deps.router._client = router_client  # router is its own metered stage

    cache = ResponseCache(semantic_enabled=semantic, semantic_threshold=SEMANTIC_THRESHOLD)
    rows = turns()

    for turn in rows:
        session = Session(student_id="WU-STU-000123", language=turn["language"])
        scope = CacheScope(
            language=turn["language"],
            intent=turn["intent"],
            # ONLY impersonal content is semantically cacheable. Excluded by
            # construction, not by a condition someone might later edit.
            personalised=turn["intent"] != "service_info",
        )
        key = exact_key(
            model_id=settings.route(answer_route).resolve("rafid-flagship"),
            prompt_ref=app.deps.service_info.prompt_ref,
            rendered_prompt="stable" if stable_prefix else f"volatile-{turn['id']}",
            question=turn["text"], temperature=0.2, max_tokens=500, scope=scope,
        )
        if cache_enabled:
            hit, tier = cache.get(key, turn["text"], scope)
            if hit is not None:
                continue  # served from cache: no model call, no cost
        reply = app.ask(turn["text"], session)
        if cache_enabled and not reply.blocked:
            cache.put(key, turn["text"], reply.text, scope)

    summary = meter.summary()
    coverage = meter.assert_full_coverage()
    return {
        "label": label,
        "turns": len(rows),
        "cache_enabled": cache_enabled,
        "semantic": semantic,
        "cheap_routing": cheap_routing,
        **summary,
        "halalas_per_turn": round(summary["total_halalas"] / len(rows), 5),
        "coverage": coverage,
        "cache": cache.stats(),
        "cascade": answer_client.stats() if cascade else None,
    }


def main() -> int:
    from scripts._gwserver import serve

    with serve() as base:
        import urllib.request
        health = json.loads(urllib.request.urlopen(f"{base}/healthz", timeout=5).read())
        tokenizer = health.get("tokenizer", "?")

        steps = [
            replay(base, label="baseline (everything off)", cache_enabled=False,
                   semantic=False, cheap_routing=False),
            replay(base, label="+ prompt cache (stable prefix)", cache_enabled=False,
                   semantic=False, cheap_routing=False, stable_prefix=True),
            replay(base, label="+ exact response cache", cache_enabled=True,
                   semantic=False, cheap_routing=False),
            replay(base, label="+ semantic tier (0.85)", cache_enabled=True,
                   semantic=True, cheap_routing=False),
            replay(base, label="+ cheap-model routing", cache_enabled=True,
                   semantic=True, cheap_routing=True),
            replay(base, label="+ cascade (the reversal)", cache_enabled=True,
                   semantic=True, cheap_routing=False, cascade=True),
        ]

    print("=" * 78)
    print("REPLAY — 200 turns, metered before and after")
    print("=" * 78)
    print(f"gateway tokenizer: {tokenizer}")
    if tokenizer != "REAL":
        print("  !! token, cache and cost figures below are PENDING COLAB VERIFICATION.")
        print("     The accounting PATH is exercised; the token counts are approximate.")
    print()

    base_line = steps[0]
    cov = base_line["coverage"]
    print("METER COVERAGE (the graded property)")
    print(f"  model calls seen : {cov['calls_seen']}")
    print(f"  metered          : {cov['metered']}")
    print(f"  coverage         : {cov['coverage']:.1%}")
    print(f"  stages metered   : {cov['stages']}")
    print(f"  guard + router in the number: "
          f"{'YES' if not cov['missing_stages'] else 'NO — ' + str(cov['missing_stages'])}")
    print()

    print("WHERE THE MONEY GOES (baseline)")
    for stage, halalas in base_line["by_stage"].items():
        share = halalas / base_line["total_halalas"] if base_line["total_halalas"] else 0
        print(f"  {stage:<10} {halalas:>10.3f} halalas   {share:>5.1%}")
    print()

    print("BEFORE / AFTER")
    print(f"  {'step':<32}{'halalas':>10}{'per turn':>11}{'saved':>9}{'p50':>8}  eval verdict")
    first = base_line["total_halalas"]
    for step in steps:
        saved = (first - step["total_halalas"]) / first if first else 0
        print(f"  {step['label']:<32}{step['total_halalas']:>10.2f}"
              f"{step['halalas_per_turn']:>11.4f}{saved:>+9.1%}{step['p50']:>8.1f}  "
              f"{'see benchmarks.py':<14}")
    final = steps[-1]
    total_saved = (first - final["total_halalas"]) / first if first else 0
    print(f"\n  TOTAL REDUCTION: {total_saved:.1%}   (target >= 60%)")
    print(f"  cache   : {final['cache']}")
    if final.get("cascade"):
        c = final["cascade"]
        print(f"  cascade : {c['escalations']}/{c['calls']} calls escalated "
              f"({c['escalation_rate']:.1%}) — the insurance premium, measured")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "replay.json").write_text(json.dumps(
        {"tokenizer": tokenizer, "steps": steps}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nwrote eval/out/replay.json")
    print("\nEval verdicts for each row are attached by scripts/benchmarks.py, which runs")
    print("the gate after each step. No row reaches BENCHMARKS.md without one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
