"""Choose the semantic-cache threshold FROM MEASURED DATA, then prove zero wrong hits.

    python scripts/eval_cache.py

A threshold somebody picked is not a threshold. This script:

  1. measures the similarity of 16 near-miss pairs — 14 that mean DIFFERENT things
     and must never collapse, 2 true paraphrases that may;
  2. prints the distribution, so the number below has visible evidence behind it;
  3. selects the lowest threshold that produces ZERO wrong hits, with margin;
  4. re-runs the whole suite at that threshold and reports hit rate AND wrong-hit
     rate together — the same pairing rule as the guards.

A wrong hit here is not a slow answer. It is a student told the wrong fee for the
wrong service, by a system that was confident because it had "seen this before".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rafid.caching.response_cache import CacheScope, ResponseCache, cosine, exact_key  # noqa: E402

PAIRS = ROOT / "data" / "near_miss_pairs.jsonl"
OUT = ROOT / "eval" / "out"
CANDIDATES = [0.70, 0.75, 0.80, 0.85, 0.88, 0.90, 0.92, 0.95]


def pairs() -> list[dict]:
    return [json.loads(line) for line in PAIRS.read_text(encoding="utf-8").splitlines() if line]


def measure(rows: list[dict]) -> list[dict]:
    return [{**r, "similarity": round(cosine(r["a"], r["b"]), 3)} for r in rows]


def run_suite(measured: list[dict], threshold: float) -> dict:
    """Every pair through a real cache at the chosen threshold."""
    cache = ResponseCache(semantic_enabled=True, semantic_threshold=threshold)
    scope = CacheScope(language="en", intent="service_info", personalised=False)
    wrong_hits, true_hits, misses = [], [], []

    for row in measured:
        s = CacheScope(language=row["language"], intent="service_info", personalised=False)
        key_a = exact_key(model_id="course-flagship", prompt_ref="answer_service.v2",
                          rendered_prompt="DIR", question=row["a"], temperature=0.2,
                          max_tokens=500, scope=s)
        cache.put(key_a, row["a"], f"ANSWER FOR: {row['a']}", s)

        key_b = exact_key(model_id="course-flagship", prompt_ref="answer_service.v2",
                          rendered_prompt="DIR", question=row["b"], temperature=0.2,
                          max_tokens=500, scope=s)
        answer, tier = cache.get(key_b, row["b"], s)

        if answer is None:
            misses.append(row["id"])
        elif row["same_answer"]:
            true_hits.append(row["id"])
        else:
            wrong_hits.append(row["id"])

    return {
        "threshold": threshold,
        "pairs": len(measured),
        "true_hits": true_hits,
        "wrong_hits": wrong_hits,
        "misses": misses,
        "wrong_hit_rate": len(wrong_hits) / len(measured),
        "cache_stats": cache.stats(),
    }


def sweep(measured: list[dict]) -> list[dict]:
    """Sweep with the LIVE cache, not pairwise.

    The first version of this compared each question only against its own pair,
    and reported zero wrong hits at 0.80. The live suite then found one: nm06's
    "What does an academic transcript cost?" collided with nm01's "How much does
    an official academic transcript cost?", which was already in the same scope
    bucket from an earlier iteration.

    That gap is the whole point of a near-miss suite. A real cache compares a
    question against EVERYTHING it holds, so a threshold validated pairwise is a
    threshold validated against a problem nobody has.
    """
    out = []
    for threshold in CANDIDATES:
        result = run_suite(measured, threshold)
        out.append({
            "threshold": threshold,
            "wrong_hits": len(result["wrong_hits"]),
            "true_hits": len(result["true_hits"]),
            "wrong_ids": result["wrong_hits"],
        })
    return out


def main() -> int:
    measured = measure(pairs())

    print("=" * 74)
    print("SEMANTIC CACHE — the threshold, chosen from the data")
    print("=" * 74)
    print("measured similarity, 16 near-miss pairs\n")
    print(f"  {'id':<6}{'same?':<7}{'sim':<7}{'family':<18}pair")
    for r in sorted(measured, key=lambda x: -x["similarity"]):
        print(f"  {r['id']:<6}{'YES' if r['same_answer'] else 'no':<7}"
              f"{r['similarity']:<7.3f}{r['family']:<18}{r['a'][:30]} / {r['b'][:26]}")

    different = [r["similarity"] for r in measured if not r["same_answer"]]
    same = [r["similarity"] for r in measured if r["same_answer"]]
    print(f"\n  DIFFERENT-meaning pairs : max similarity {max(different):.3f}")
    print(f"  SAME-meaning pairs      : min similarity {min(same):.3f}")
    gap = min(same) - max(different)
    print(f"  separation              : {gap:+.3f}")

    print("\nthreshold sweep — each candidate run through the LIVE cache,")
    print("all-vs-all, not pairwise (see the docstring on sweep()).")
    print(f"  {'threshold':<12}{'wrong hits':<13}{'true hits':<12}offenders")
    table = sweep(measured)
    for row in table:
        print(f"  {row['threshold']:<12}{row['wrong_hits']:<13}{row['true_hits']:<12}"
              f"{','.join(row['wrong_ids']) or '-'}")

    safe = [r for r in table if r["wrong_hits"] == 0]
    if not safe:
        print("\nNo candidate threshold gives zero wrong hits. The semantic tier stays OFF.")
        return 1
    chosen = min(safe, key=lambda r: r["threshold"])["threshold"]
    print(f"\nchosen threshold: {chosen}")
    print(f"  the lowest candidate with zero wrong hits in the live suite.")
    print(f"  (max different-meaning PAIR similarity is {max(different):.3f}; the live")
    print(f"   threshold sits higher because a cached question can collide with any")
    print(f"   other cached question, not only its pair.)")

    print("\nsuite at the chosen threshold")
    result = run_suite(measured, chosen)
    print(f"  pairs           : {result['pairs']}")
    print(f"  true hits       : {len(result['true_hits'])}  {result['true_hits']}")
    print(f"  WRONG HITS      : {len(result['wrong_hits'])}  {result['wrong_hits'] or '(none)'}")
    print(f"  wrong-hit rate  : {result['wrong_hit_rate']:.1%}   (target 0%)")
    print(f"  hit rate        : {result['cache_stats']['hit_rate']:.1%}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cache_eval.json").write_text(json.dumps(
        {"measured": measured, "sweep": table, "chosen_threshold": chosen, "suite": result},
        ensure_ascii=False, indent=2), encoding="utf-8")

    ok = result["wrong_hits"] == []
    print("\n" + ("PASS — zero wrong hits at the chosen threshold"
                  if ok else "FAIL — wrong hits at the chosen threshold"))
    print("Reported as a pair, always: a hit rate without a wrong-hit rate is not a result.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
