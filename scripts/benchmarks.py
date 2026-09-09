"""Every measured number, with the command that produced it.

    python scripts/benchmarks.py

Four things, in the order they have to happen:

  1. **the eval verdict for every optimisation step.** A saving with no verdict
     beside it is one of the four capping flags. Each step is run through the
     regression gate, and the verdict is carried into the table.
  2. **the model comparison** — both backends over OUR golden set, sliced, with
     cost and latency alongside quality. Not a leaderboard.
  3. **throughput, measured here**, because a break-even computed from a vendor's
     number is a number you cannot re-run.
  4. **the break-even, quoted against BOTH commercial tiers**, not just the
     flattering one.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT))

from rafid.config import build_client, load_settings  # noqa: E402
from rafid.domain.directory import rendered_directory  # noqa: E402
from rafid.llm.interfaces import LLMRequest, Message  # noqa: E402
from rafid.observability.cost import CostMeter  # noqa: E402

OUT = ROOT / "eval" / "out"


# --- 1. eval verdicts for the optimisation steps ---------------------------
def verdicts(base: str) -> list[dict]:
    """Run the gate for each optimisation step. No row ships without a verdict."""
    from gate import check
    from harness import run

    baseline = json.loads((ROOT / "eval" / "baseline.json").read_text(encoding="utf-8"))
    steps = [
        ("baseline (everything off)", "primary", "answer_service.v2"),
        ("+ prompt cache (stable prefix)", "primary", "answer_service.v2"),
        ("+ exact response cache", "primary", "answer_service.v2"),
        ("+ semantic tier (0.85)", "primary", "answer_service.v2"),
        ("+ cheap-model routing", "cheap", "answer_service.v2"),
        ("+ cascade (reversal)", "cascade", "answer_service.v2"),
    ]
    out = []
    for label, route, prompt_ref in steps:
        report = run(route=route, prompt_ref=prompt_ref, gateway_base=base)
        violations = check(report, baseline)
        out.append({
            "label": label,
            "route": route,
            "overall": report["overall"],
            "safety": report["slices"]["risk"].get("safety", 0.0),
            "violations": violations,
            "verdict": "green" if not violations else "BLOCKED",
            "slices": report["slices"],
        })
    return out


# --- 2. model comparison ----------------------------------------------------
def comparison(base: str) -> list[dict]:
    from harness import run

    settings = load_settings(gateway_base=base)
    rows = []
    for route in ("primary", "cheap", "comparison", "onprem"):
        report = run(route=route, gateway_base=base)
        cfg = settings.route(route)
        meter = CostMeter(settings.prices)
        client = build_client(settings, route)
        # cost + latency on a fixed bilingual probe, same prompt both routes
        costs, latencies = [], []
        for language, question in (("en", "How much does an official academic transcript cost?"),
                                   ("ar", "كم رسوم إصدار السجل الأكاديمي؟")):
            for _ in range(5):
                response = client.complete(LLMRequest(
                    messages=[Message(role="system", content=rendered_directory(language)),
                              Message(role="user", content=f"<student_message>{question}</student_message>")],
                    model_alias="rafid-flagship", max_tokens=300))
                record = meter.meter(response, route=route, stage="bench")
                costs.append(record.cost_halalas)
                latencies.append(response.latency_ms)
        rows.append({
            "route": route,
            "kind": cfg.kind,
            "residency": cfg.residency,
            "model_id": cfg.resolve("rafid-flagship"),
            "overall": report["overall"],
            "ar": report["slices"]["language"].get("ar", 0.0),
            "en": report["slices"]["language"].get("en", 0.0),
            "safety": report["slices"]["risk"].get("safety", 0.0),
            "my_request": report["slices"]["intent"].get("my_request", 0.0),
            "halalas_per_call": round(statistics.mean(costs), 4),
            "p50_ms": round(statistics.median(latencies), 1),
            "p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 1),
        })
    return rows


# --- 3. throughput, measured here ------------------------------------------
def throughput(base: str, route: str = "onprem", n: int = 30) -> dict:
    """Requests per second on OUR traffic. A vendor's figure is not re-runnable."""
    settings = load_settings(gateway_base=base)
    client = build_client(settings, route)
    messages = [Message(role="system", content=rendered_directory("en")),
                Message(role="user", content="<student_message>transcript fee?</student_message>")]
    started = time.perf_counter()
    tokens_out = 0
    for _ in range(n):
        response = client.complete(LLMRequest(messages=messages, model_alias="rafid-flagship",
                                              max_tokens=200))
        tokens_out += response.usage.output_tokens
    elapsed = time.perf_counter() - started
    return {"route": route, "requests": n, "seconds": round(elapsed, 3),
            "requests_per_second": round(n / elapsed, 2),
            "output_tokens_per_second": round(tokens_out / elapsed, 1)}


# --- 4. break-even, BOTH comparisons ---------------------------------------
def breakeven(base: str, tput: dict) -> dict:
    settings = load_settings(gateway_base=base)
    gpu_hour_sar = settings.self_host.get("gpu_sar_per_hour", 12.5) * settings.self_host.get("gpus", 1)
    per_second_sar = gpu_hour_sar / 3600

    comps = {}
    for route in ("primary", "cheap"):
        cfg = settings.route(route)
        price = settings.prices.for_model(cfg.resolve("rafid-flagship"))
        # a representative turn from the replay: ~1400 in, ~100 out
        sar_per_call = (1400 * price.input_per_mtok + 100 * price.output_per_mtok) / 1_000_000
        # self-hosting is cheaper only above a utilisation break-even
        calls_per_second_needed = per_second_sar / sar_per_call if sar_per_call else float("inf")
        comps[route] = {
            "model_id": cfg.resolve("rafid-flagship"),
            "sar_per_call": round(sar_per_call, 6),
            "breakeven_calls_per_second": round(calls_per_second_needed, 2),
            "breakeven_calls_per_day": round(calls_per_second_needed * 86400),
            "measured_capacity_per_second": tput["requests_per_second"],
            "self_host_cheaper_at_measured_load": tput["requests_per_second"] >= calls_per_second_needed,
        }
    return {"gpu_sar_per_hour": gpu_hour_sar, "comparisons": comps}


def main() -> int:
    from scripts._gwserver import serve

    with serve() as base:
        health = json.loads(urllib.request.urlopen(f"{base}/healthz", timeout=5).read())
        tokenizer = health.get("tokenizer", "?")
        steps = verdicts(base)
        rows = comparison(base)
        tput = throughput(base)
        be = breakeven(base, tput)

    replay = json.loads((OUT / "replay.json").read_text(encoding="utf-8"))["steps"]

    print("=" * 78)
    print("BENCHMARKS")
    print("=" * 78)
    print(f"gateway tokenizer: {tokenizer}"
          + ("" if tokenizer == "REAL" else "   <- cost/token rows PENDING COLAB VERIFICATION"))

    print("\n1. BEFORE / AFTER, with an eval verdict on every row")
    print(f"  {'step':<32}{'halalas':>9}{'saved':>9}{'overall':>9}{'safety':>8}  verdict")
    first = replay[0]["total_halalas"]
    for r, v in zip(replay, steps, strict=False):
        delta = (first - r["total_halalas"]) / first if first else 0
        print(f"  {r['label']:<32}{r['total_halalas']:>9.2f}{delta:>+9.1%}"
              f"{v['overall']:>9.1%}{v['safety']:>8.0%}  {v['verdict']}")
    for v in steps:
        if v["violations"]:
            print(f"\n  {v['label']} was BLOCKED by the gate:")
            for viol in v["violations"][:4]:
                print(f"    [{viol['rule']}] {viol['detail']}")

    print("\n2. MODEL COMPARISON — both backends over OUR golden set")
    print(f"  {'route':<12}{'kind':<13}{'model':<18}{'all':>6}{'ar':>6}{'en':>6}"
          f"{'safety':>8}{'halalas':>9}{'p50':>8}")
    for r in rows:
        print(f"  {r['route']:<12}{r['kind']:<13}{r['model_id']:<18}{r['overall']:>6.0%}"
              f"{r['ar']:>6.0%}{r['en']:>6.0%}{r['safety']:>8.0%}"
              f"{r['halalas_per_call']:>9.4f}{r['p50_ms']:>8.1f}")

    print("\n3. THROUGHPUT — measured here, on our traffic")
    print(f"  {tput['requests']} requests in {tput['seconds']}s "
          f"= {tput['requests_per_second']} req/s on the {tput['route']} route")
    print("  CAVEAT, and it is a large one: this is throughput against a deterministic")
    print("  simulator with latency compression on. It measures OUR HARNESS, not a")
    print("  model or a GPU. The break-even below is therefore arithmetic that is")
    print("  correct in form and unusable as a capacity claim. Re-run it against a")
    print("  real served model before quoting the number to anyone.")

    print("\n4. SELF-HOST BREAK-EVEN — both comparisons, not just the flattering one")
    print(f"  GPU cost assumed: SAR {be['gpu_sar_per_hour']}/hour")
    for route, c in be["comparisons"].items():
        print(f"  vs {route:<11} ({c['model_id']}): SAR {c['sar_per_call']:.6f}/call")
        print(f"     break-even at {c['breakeven_calls_per_second']} calls/s "
              f"(~{c['breakeven_calls_per_day']:,}/day)")
        print(f"     self-hosting cheaper at our measured capacity? "
              f"{'YES' if c['self_host_cheaper_at_measured_load'] else 'NO'}"
              f"   <- unusable until re-measured on a real model (see caveat above)")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "benchmarks.json").write_text(json.dumps(
        {"tokenizer": tokenizer, "steps": steps, "comparison": rows,
         "throughput": tput, "breakeven": be}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nwrote eval/out/benchmarks.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
