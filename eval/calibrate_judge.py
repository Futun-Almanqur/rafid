"""Judge calibration. A judge is an instrument: no kappa, no authority.

    python eval/calibrate_judge.py

Percent agreement is not enough on its own. When 60% of the labels are 1.0, an
instrument that always says 1.0 scores 60% agreement and knows nothing. Cohen's
kappa corrects for the agreement you would get by chance, which is why the bar is
stated in kappa (>= 0.6) and not in percent.

Two rubric versions are scored here, and the difference between them is the whole
lesson: when the judge disagrees with the humans, **fix the rubric, not the
humans**. v1 -> v2 is a rubric edit and nothing else.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from rafid.domain.directory import rendered_directory, unsupported_amounts  # noqa: E402

LABELS = ROOT / "eval" / "golden" / "human_labels.jsonl"
OUT = ROOT / "eval" / "out"
KAPPA_BAR = 0.6

DECLINE_MARKERS = ["i don't have that information", "i won't guess", "not in the service directory",
                   "لا تتوفر لدي", "لن أخمّن", "غير متوفرة في دليل الخدمات"]


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Pure Python, twelve lines, no scikit-learn. It is a contingency table."""
    categories = sorted(set(a) | set(b))
    n = len(a)
    observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    expected = sum((a.count(c) / n) * (b.count(c) / n) for c in categories)
    if expected >= 1.0:
        return 1.0 if observed >= 1.0 else 0.0
    return (observed - expected) / (1 - expected)


def judge_v1(answer: str, language: str) -> float:
    """Rubric v1: 'score 0.0 if the answer states something the directory does
    not support'. Applied literally — and it reads a refusal as unsupported,
    because a refusal states nothing the directory supports either."""
    invented = unsupported_amounts(answer, language)
    if invented:
        return 0.0
    directory = rendered_directory(language)
    stated = [tok for tok in answer.split() if tok.strip("-:،.") in directory]
    if len(stated) >= 3:
        return 1.0
    return 0.0  # <- the v1 defect: nothing checkable == unsupported


def judge_v2(answer: str, language: str) -> float:
    """Rubric v2: refusals named explicitly, scale anchored on AMOUNTS."""
    invented = unsupported_amounts(answer, language)
    if invented:
        return 0.0
    low = answer.lower()
    if any(m in low for m in DECLINE_MARKERS):
        return 1.0  # an honest refusal is fully grounded
    from rafid.domain.directory import _amounts, load_directory

    if _amounts(answer) & (load_directory().amounts("en") | load_directory().amounts("ar")):
        return 1.0
    return 0.5  # directory-shaped, no amount to check


def bucket(score: float) -> str:
    return {1.0: "grounded", 0.5: "partial", 0.0: "ungrounded"}[score]


def calibrate(rubric: str) -> dict:
    fn = {"groundedness.v1": judge_v1, "groundedness.v2": judge_v2}[rubric]
    rows = [json.loads(line) for line in LABELS.read_text(encoding="utf-8").splitlines() if line]

    human = [bucket(r["human_score"]) for r in rows]
    machine = [bucket(fn(r["answer"], r["language"])) for r in rows]
    agree = sum(1 for h, m in zip(human, machine, strict=True) if h == m)

    disagreements = [
        {"case_id": r["case_id"], "human": h, "judge": m, "answer": r["answer"][:70],
         "reason": r["label_reason"]}
        for r, h, m in zip(rows, human, machine, strict=True) if h != m
    ]
    return {
        "rubric": rubric,
        "n": len(rows),
        "percent_agreement": agree / len(rows),
        "kappa": cohen_kappa(human, machine),
        "disagreements": disagreements,
    }


def main() -> int:
    results = [calibrate("groundedness.v1"), calibrate("groundedness.v2")]

    print("=" * 74)
    print("JUDGE CALIBRATION — 40 hand-scored answers")
    print("=" * 74)
    for r in results:
        verdict = "PASS" if r["kappa"] >= KAPPA_BAR else "below the bar"
        print(f"{r['rubric']:<20} agreement={r['percent_agreement']:.0%}  "
              f"kappa={r['kappa']:.2f}   ({verdict}, bar {KAPPA_BAR})")

    v1, v2 = results
    print()
    print(f"v1 disagreed with the humans on {len(v1['disagreements'])} answers.")
    for d in v1["disagreements"][:4]:
        print(f"  {d['case_id']}  human={d['human']:<10} judge={d['judge']:<10} {d['answer'][:48]}")
    if len(v1["disagreements"]) > 4:
        print(f"  ... and {len(v1['disagreements']) - 4} more, the same shape")
    kinds = {}
    for d in v1["disagreements"]:
        key = f"human={d['human']} judge={d['judge']}"
        kinds[key] = kinds.get(key, 0) + 1
    print()
    print("Two distinct v1 defects, not one:")
    for key, count in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"  {count} x  {key}")
    print()
    print("  1. Honest refusals scored 0.0. v1's rule — 'score 0.0 if the answer")
    print("     states something the directory does not support' — reads a refusal as")
    print("     unsupported, because a refusal states nothing at all.")
    print("  2. Vague directory-shaped answers scored 1.0. v1 had no way to say")
    print("     'no amount to check', so anything echoing directory words passed.")
    print()
    print("We fixed the RUBRIC, not the labels. v2 names refusals explicitly and")
    print("anchors the scale on AMOUNTS, which is what actually harms a student.")
    print()
    print(f"kappa moved {v1['kappa']:.2f} -> {v2['kappa']:.2f} on a rubric edit and nothing else.")
    print()
    print(f"Stated honestly: v1 already cleared the {KAPPA_BAR} bar. It was not unusable —")
    print("it was miscalibrated in a specific, nameable way, and the calibration run is")
    print("what made that visible. That is what an instrument check is for.")
    print()
    print("The judge is a TRACKING metric. It gates nothing, at any kappa.")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "judge_calibration.json").write_text(
        json.dumps({"bar": KAPPA_BAR, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("\nwrote eval/out/judge_calibration.json")
    return 0 if v2["kappa"] >= KAPPA_BAR else 1


if __name__ == "__main__":
    sys.exit(main())
