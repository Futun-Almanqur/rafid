"""Prove the gateway's lifecycle: it starts, it dies, and it starts again.

    python scripts/verify_lifecycle.py

Seven steps, on ONE port, with no sleeps used as evidence:

  1. start the gateway on a chosen port
  2. /healthz responds
  3. terminate the process GROUP we own
  4. poll until that SAME port refuses connections
  5. restart on the SAME port
  6. /healthz responds again
  7. a grounded Wadi answer still succeeds

Why one port and not a fresh one: a restart onto a different port proves nothing
about whether the first process is gone. The whole claim is that the original
process released the socket, so the socket is what has to be re-checked.

This runs the same functions the notebook's §0 and §0.4 cells call, so a pass
here is a pass for the code path the notebook actually executes.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.gateway_process import (  # noqa: E402
    free_port,
    healthz,
    port_is_open,
    start_gateway,
    stop_gateway,
    wait_until_port_closed,
)

from rafid.config import build_client, load_settings  # noqa: E402
from rafid.domain.directory import load_directory, rendered_directory  # noqa: E402
from rafid.llm import LLMRequest, Message  # noqa: E402
from rafid.prompts.registry import load_prompt  # noqa: E402

EXPECTED_FEE = "SAR 60 per copy"


def grounded_answer(port: int) -> str:
    """A real request through the adapter — including its pooled connection.

    Deliberately made BEFORE the shutdown as well as after: an open keep-alive
    connection is exactly what can hold a graceful shutdown open, so the proof
    is worth nothing if the port is idle when we kill it.
    """
    settings = load_settings(gateway_base=f"http://127.0.0.1:{port}")
    client = build_client(settings, "primary")
    prompt = load_prompt("answer_service.v2")
    reply = client.complete(LLMRequest(
        messages=[
            Message(role="system", content=prompt.render(
                service_directory=rendered_directory("en"),
                registrar_contact=load_directory().contact("en"))),
            Message(role="user", content="<student_message>How much does an official "
                                         "academic transcript cost?</student_message>"),
        ],
        model_alias="rafid-flagship",
        max_tokens=300,
    ))
    return reply.text or ""


def main() -> int:
    port = free_port()
    failures: list[str] = []

    print("=" * 74)
    print(f"GATEWAY LIFECYCLE — one port ({port}), start, kill, prove dead, restart")
    print("=" * 74)

    # 1 -------------------------------------------------------------------
    proc = start_gateway(port)
    print(f"1. started        : pid={proc.pid} pgid=owned  port={port}")

    # 2 -------------------------------------------------------------------
    health = healthz(port)
    print(f"2. GET /healthz   : {health}")
    if not health.get("ok"):
        failures.append("healthz did not report ok on the first start")

    # an open pooled connection, so the shutdown has something to hang on
    first_answer = grounded_answer(port)
    print(f"   grounded answer: {first_answer.splitlines()[1].strip()}")

    # 3 -------------------------------------------------------------------
    result = stop_gateway(proc, port)
    print(f"3. terminated     : returncode={result['returncode']} "
          f"escalated_to_sigkill={result['escalated_to_sigkill']}")

    # 4 -------------------------------------------------------------------
    closed = result["port_closed"] and wait_until_port_closed(port, timeout=5)
    still_open = port_is_open(port)
    print(f"4. port is dead   : port_closed={closed} tcp_connect_succeeds={still_open}")
    if still_open or not closed:
        failures.append(
            f"port {port} still accepts connections after the owned process group "
            "was terminated — the restart proof would be meaningless"
        )

    # 5 -------------------------------------------------------------------
    proc2 = start_gateway(port)
    print(f"5. restarted      : pid={proc2.pid} (was {proc.pid}) on the SAME port {port}")
    if proc2.pid == proc.pid:
        failures.append("the restarted pid equals the original — nothing was replaced")

    # 6 -------------------------------------------------------------------
    health2 = healthz(port)
    print(f"6. GET /healthz   : {health2}")
    if not health2.get("ok"):
        failures.append("healthz did not report ok after the restart")

    # 7 -------------------------------------------------------------------
    second_answer = grounded_answer(port)
    print(f"7. grounded answer: {second_answer.splitlines()[1].strip()}")
    if EXPECTED_FEE not in second_answer:
        failures.append("the restarted gateway did not answer from the directory")

    stop_gateway(proc2, port)

    print()
    if failures:
        print("FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("PASS  the original process really released the port, and a fresh process")
    print("      answered from the directory on that same port. No leftover state.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
