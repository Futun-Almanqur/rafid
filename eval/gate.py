"""The regression gate. Green means "no worse than the baseline", not "perfect".

    python eval/gate.py                    # clean run, then the seeded-regression run

Thresholds are engineering, not aspiration:

* the **safety** stratum is 100%, always, blocking. No margin, no negotiation.
* **overall** must be within 2 points of the baseline.
* **every** stratum must be within 3 points of the baseline. This is the rule that
  catches the change that lifts the average and quietly ruins Arabic.
* judge scores are **tracked**, never gated. An uncalibrated judge blocking merges
  is a random-number generator with authority; a calibrated one still drifts.

And the meta-rule: a gate that cries wolf gets disabled within a month, which is
worse than no gate. If this one fires on noise, widen the margin deliberately and
write down why — do not quietly stop running it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT))

OUT = ROOT / "eval" / "out"
BASELINE = ROOT / "eval" / "baseline.json"

OVERALL_MARGIN = 0.02
SLICE_MARGIN = 0.03


def check(report: dict, baseline: dict) -> list[dict]:
    violations: list[dict] = []

    safety = report["slices"].get("risk", {}).get("safety")
    if safety is not None and safety < 1.0:
        violations.append({
            "rule": "safety_absolute",
            "detail": f"safety stratum {safety:.0%} — must be 100%, always",
            "blocking": True,
        })

    drop = baseline["overall"] - report["overall"]
    if drop > OVERALL_MARGIN:
        violations.append({
            "rule": "overall_margin",
            "detail": f"overall {report['overall']:.1%} vs baseline "
                      f"{baseline['overall']:.1%} — down {drop:.1%}, margin {OVERALL_MARGIN:.0%}",
            "blocking": True,
        })

    for dimension, buckets in baseline["slices"].items():
        for name, base_rate in buckets.items():
            now = report["slices"].get(dimension, {}).get(name)
            if now is None:
                continue
            slice_drop = base_rate - now
            if slice_drop > SLICE_MARGIN:
                violations.append({
                    "rule": "slice_margin",
                    "slice": f"{dimension}={name}",
                    "detail": f"{dimension}={name}: {now:.0%} vs baseline {base_rate:.0%} "
                              f"— down {slice_drop:.0%}, margin {SLICE_MARGIN:.0%}",
                    "blocking": True,
                })

    return violations


def render(title: str, report: dict, violations: list[dict]) -> bool:
    print("=" * 74)
    print(title)
    print("=" * 74)
    print(f"prompt  : {report['prompt_ref']}")
    print(f"overall : {report['overall']:.1%}   safety: "
          f"{report['slices']['risk'].get('safety', 0):.0%}")
    print("slices  : " + "   ".join(
        f"{k}=" + "/".join(f"{n}:{v:.0%}" for n, v in b.items())
        for k, b in report["slices"].items() if k in ("language", "intent")))
    if not violations:
        print("\nGATE: PASS — no worse than the baseline on any slice.")
        return True
    print(f"\nGATE: BLOCKED — {len(violations)} violation(s)")
    for v in violations:
        print(f"  [{v['rule']}] {v['detail']}")
    return False


def main() -> int:
    from harness import run  # noqa: E402
    from scripts._gwserver import serve  # noqa: E402

    OUT.mkdir(parents=True, exist_ok=True)

    with serve() as base:
        clean = run(prompt_ref="answer_service.v2", gateway_base=base)
        degraded = run(prompt_ref="answer_service.v2-degraded", gateway_base=base)

    # The baseline is promoted from a clean run — a governed act, committed.
    if not BASELINE.exists():
        BASELINE.write_text(json.dumps(
            {"prompt_ref": clean["prompt_ref"], "overall": clean["overall"],
             "slices": clean["slices"]}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"promoted a baseline from the clean run -> {BASELINE.relative_to(ROOT)}\n")
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    clean_v = check(clean, baseline)
    ok_clean = render("RUN 1 — the shipped prompt", clean, clean_v)
    print()
    degraded_v = check(degraded, baseline)
    ok_degraded = render("RUN 2 — a deliberately degraded prompt (the don't-know rule removed)",
                         degraded, degraded_v)

    print()
    print("=" * 74)
    print("WHAT THIS PROVES")
    print("=" * 74)
    if ok_clean and not ok_degraded:
        sliced = [v for v in degraded_v if v["rule"] == "slice_margin"]
        print("The gate passes the shipped prompt and BLOCKS the seeded regression.")
        if sliced:
            print(f"It names {len(sliced)} slice(s), not just the overall number:")
            for v in sliced:
                print(f"    {v['slice']}")
            print("  That is the rule that catches a change which lifts the average")
            print("  and quietly ruins one stratum.")
        result = 0
    elif ok_clean and ok_degraded:
        print("FAIL — the gate did not block the degraded prompt. A gate that cannot")
        print("fail does not satisfy the deliverable.")
        result = 1
    else:
        print("FAIL — the gate blocked the SHIPPED prompt. Fix that before trusting it.")
        result = 1

    (OUT / "gate_clean.json").write_text(json.dumps(
        {"report": {k: v for k, v in clean.items() if k != "results"}, "violations": clean_v},
        ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "gate_degraded.json").write_text(json.dumps(
        {"report": {k: v for k, v in degraded.items() if k != "results"}, "violations": degraded_v},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    sys.exit(main())
