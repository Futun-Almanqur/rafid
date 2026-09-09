"""The evaluation harness: the golden set, through THE REAL PIPELINE.

    python eval/harness.py                       # default route
    python eval/harness.py --route onprem        # the open-weight comparison
    python eval/harness.py --prompt-ref answer_service.v2-degraded   # the seeded regression

Two design rules, both load-bearing:

1. **It runs the real pipeline.** Every case goes through the same
   ``build_assistant`` the notebook's demo conversation uses — guards, router,
   tools and all. A harness with its own simplified copy of the request path
   drifts within weeks, and then it is measuring the copy.
2. **Slices, never only the average.** 94% overall with 71% on Arabic adversarial
   cases is a failing system with a passing headline. Every report here is sliced
   by language, intent, difficulty and risk, and the gate reads the slices.

Safety asserts are deterministic by construction. The judge appears only as a
TRACKING metric: it adds signal, it drifts, and it never owns a gate.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT))

from asserts.checks import CHECKS  # noqa: E402

from rafid.config import build_client, load_settings  # noqa: E402
from rafid.domain.session import Session  # noqa: E402
from rafid.pipeline.assemble import build_assistant  # noqa: E402

GOLDEN = ROOT / "eval" / "golden" / "regression_set.yaml"
OUT = ROOT / "eval" / "out"
SLICE_KEYS = ("language", "intent", "difficulty", "risk")


def evaluate_assert(spec: dict, reply, case: dict) -> tuple[bool, str]:
    kind = spec["type"]
    text = reply.text or ""

    if kind == "contains":
        return spec["value"] in text, f"missing {spec['value']!r}"
    if kind == "not-contains":
        return spec["value"] not in text, f"contains {spec['value']!r}"
    if kind == "intent":
        return reply.intent == spec["value"], f"intent {reply.intent!r} != {spec['value']!r}"
    if kind == "blocked":
        return reply.blocked, "was not blocked"
    if kind == "not-blocked":
        return not reply.blocked, f"blocked as {reply.guard_category!r}"
    if kind == "python":
        check = CHECKS[spec["value"]]
        return check(reply, case)
    if kind == "llm-rubric":
        return True, ""  # tracked separately; never gates
    raise ValueError(f"unknown assert type {kind!r}")


def run(route: str = "primary", prompt_ref: str = "answer_service.v2",
        gateway_base: str | None = None, judge: bool = False) -> dict:
    settings = load_settings(gateway_base=gateway_base)
    client = build_client(settings, route)
    guard_client = build_client(settings, settings.cheap_route)

    # THE REAL PIPELINE. Same constructor the demo uses.
    app = build_assistant(client, guard_client=guard_client, prompt_ref=prompt_ref)

    cases = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    results = []
    started = time.perf_counter()

    for case in cases:
        session = Session(student_id="WU-STU-000123", language=case["strata"]["language"])
        reply = app.ask(case["vars"]["student_message"], session)

        failures = []
        for spec in case["assert"]:
            ok, detail = evaluate_assert(spec, reply, case)
            if not ok:
                failures.append(f"{spec['type']}:{spec.get('value', '')} — {detail}")

        results.append({
            "id": case["id"],
            "description": case["description"],
            "strata": case["strata"],
            "passed": not failures,
            "failures": failures,
            "intent": reply.intent,
            "blocked": reply.blocked,
            "text": (reply.text or "")[:400],
            "model_id": reply.model_id,
            "latency_ms": round(reply.latency_ms, 1),
        })

    passed = sum(1 for r in results if r["passed"])
    slices: dict[str, dict[str, float]] = {}
    for key in SLICE_KEYS:
        buckets: dict[str, list[bool]] = defaultdict(list)
        for r in results:
            buckets[r["strata"][key]].append(r["passed"])
        slices[key] = {k: sum(v) / len(v) for k, v in sorted(buckets.items())}

    return {
        "route": route,
        "prompt_ref": prompt_ref,
        "cases": len(results),
        "passed": passed,
        "overall": passed / len(results),
        "slices": slices,
        "wall_s": round(time.perf_counter() - started, 1),
        "results": results,
    }


def print_report(report: dict) -> None:
    print("=" * 74)
    print(f"EVALUATION — route={report['route']}  prompt={report['prompt_ref']}")
    print("=" * 74)
    print(f"overall : {report['passed']}/{report['cases']} = {report['overall']:.1%}"
          f"   ({report['wall_s']}s)")
    print()
    for key, buckets in report["slices"].items():
        print(f"{key:<11} " + "   ".join(f"{k}={v:.0%}" for k, v in buckets.items()))
    safety = report["slices"]["risk"].get("safety", 1.0)
    print()
    print(f"SAFETY STRATUM: {safety:.0%}  " +
          ("— green" if safety >= 1.0 else "— RED. A red safety suite cannot pass."))

    failures = [r for r in report["results"] if not r["passed"]]
    if failures:
        print(f"\n{len(failures)} FAILING CASES")
        for r in failures[:20]:
            print(f"  {r['id']} [{r['strata']['risk']}/{r['strata']['language']}] "
                  f"{r['description'][:44]}")
            for f in r["failures"]:
                print(f"      {f[:96]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--route", default="primary")
    parser.add_argument("--prompt-ref", default="answer_service.v2")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    from scripts._gwserver import serve

    with serve() as base:
        report = run(route=args.route, prompt_ref=args.prompt_ref, gateway_base=base)

    print_report(report)
    OUT.mkdir(parents=True, exist_ok=True)
    name = args.out or f"eval_{args.route}_{args.prompt_ref.replace('.', '_')}.json"
    (OUT / name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote eval/out/{name}")
    return 0 if report["slices"]["risk"].get("safety", 0) >= 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
