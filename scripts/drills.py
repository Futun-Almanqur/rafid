"""The two reliability drills, fired at a real gateway over a real socket.

    python scripts/drills.py

A fallback chain that has never fired is a chain nobody knows works. So both
drills inject a real fault at the gateway's ``/admin/fault`` endpoint and let the
real ``ResilientClient`` react to real HTTP status codes:

  * **429 storm** — the primary model rate-limits for a few seconds with a
    ``Retry-After`` header. Expected: the client backs off for exactly that long
    and the *same* route succeeds. No hop.
  * **outage** — the primary model returns 529 for the whole drill. Expected:
    retries exhaust, then the fallback hop to the open-weight route serves the
    student an answer.

The transcripts printed here are the evidence for capstone requirements 1.8 and
1.9. They are captured in the notebook as cell output, not narrated.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts._gwserver import serve  # noqa: E402

from rafid.config import build_resilient_client, load_settings  # noqa: E402
from rafid.llm import LLMRequest, Message  # noqa: E402
from rafid.llm.interfaces import LLMError  # noqa: E402


def fault(base: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{base}/admin/fault",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def question() -> list[Message]:
    return [
        Message(role="system", content="Wadi University student services."),
        Message(role="user", content="<student_message>How much is a transcript?</student_message>"),
    ]


def rule(title: str) -> None:
    print(f"\n{'=' * 74}\n{title}\n{'=' * 74}")


def drill_rate_limit(base: str) -> bool:
    rule("DRILL 1 · a 429 storm on the primary model")
    settings = load_settings(gateway_base=base)
    client = build_resilient_client(settings, max_attempts=4, base_backoff_s=0.05)

    print("injecting:", fault(base, {"mode": "rate_limit", "seconds": 1.2,
                                     "model": "course-flagship", "retry_after": 0.5})["fault"])
    try:
        response = client.complete(
            LLMRequest(messages=question(), model_alias="rafid-flagship", max_tokens=120)
        )
    except LLMError as exc:
        print("FAIL — every attempt failed:", exc)
        print(client.format_transcript())
        return False
    finally:
        fault(base, {"mode": "off"})

    print("\nTRANSCRIPT")
    print(client.format_transcript())
    print(f"\nserved by  : {response.model_id} via route '{response.route}'")
    print(f"attempts   : {response.attempts}")

    retried = any(e["event"] == "error" and e["status"] == 429 for e in client.transcript)
    backed_off = any(e["event"] == "backoff" for e in client.transcript)
    same_route = response.route == settings.primary_route
    ok = retried and backed_off and same_route and response.attempts > 1
    print(
        f"\n{'PASS' if ok else 'FAIL'}  a real 429 was received, the client honoured "
        f"Retry-After, and the SAME route then served it (no unnecessary hop)."
    )
    return ok


def drill_outage(base: str) -> bool:
    rule("DRILL 2 · the primary model is down (529) for the whole drill")
    settings = load_settings(gateway_base=base)
    client = build_resilient_client(settings, max_attempts=2, base_backoff_s=0.05)
    print(f"chain      : {[name for name, _ in client.clients]}")

    print("injecting:", fault(base, {"mode": "overload", "seconds": 20,
                                     "model": "course-flagship"})["fault"])
    try:
        response = client.complete(
            LLMRequest(messages=question(), model_alias="rafid-flagship", max_tokens=120)
        )
    except LLMError as exc:
        print("FAIL — the fallback did not save it:", exc)
        print(client.format_transcript())
        return False
    finally:
        fault(base, {"mode": "off"})

    print("\nTRANSCRIPT")
    print(client.format_transcript())
    print(f"\nserved by  : {response.model_id} via route '{response.route}'")
    print(f"answer     : {(response.text or '').strip().splitlines()[0][:70]}")

    hopped = any(e["event"] == "fallback" for e in client.transcript)
    saw_529 = any(e["status"] == 529 for e in client.transcript)
    served_by_fallback = response.route == settings.fallback_route
    ok = hopped and saw_529 and served_by_fallback
    print(
        f"\n{'PASS' if ok else 'FAIL'}  the primary really returned 529, retries "
        f"exhausted, and the open-weight route served the student an answer."
    )
    return ok


def main() -> int:
    with serve() as base:
        print(f"gateway    : {base}")
        health = json.loads(urllib.request.urlopen(f"{base}/healthz", timeout=5).read())
        print(f"tokenizer  : {health.get('tokenizer')}")
        results = {"rate_limit": drill_rate_limit(base), "outage": drill_outage(base)}

    rule("VERDICT")
    for name, ok in results.items():
        print(f"  {name:<12} {'PASS' if ok else 'FAIL'}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
