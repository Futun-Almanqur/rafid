"""Reliability policy in ONE place: retry, then fall back to the next route.

Two rules the course states and this file encodes:

* **retry only what is worth retrying.** A 400 retried three times is three times
  the bug and three times the cost. ``LLMError.retryable`` decides, and it is set
  from the HTTP status by the adapter — never guessed here.
* **honour ``Retry-After``.** A provider telling you when to come back is the
  cheapest signal in the system, and backing off blindly ignores it.

The fallback hop is the part most projects have and never exercise. ``drill()``
in ``scripts/drills.py`` fires a real fault at the gateway so the transcript
exists, because a chain that has never fired is a chain nobody knows works.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from rafid.llm.interfaces import LLMClient, LLMError, LLMRequest, LLMResponse
from rafid.observability import get_logger

log = get_logger(__name__)


class ResilientClient:
    """Wraps an ordered list of (route_name, client). Retries, then hops."""

    def __init__(
        self,
        clients: list[tuple[str, LLMClient]],
        *,
        max_attempts: int = 3,
        base_backoff_s: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not clients:
            raise ValueError("ResilientClient needs at least one route")
        self.clients = clients
        self.max_attempts = max_attempts
        self.base_backoff_s = base_backoff_s
        self._sleep = sleep
        self.transcript: list[dict] = []

    @property
    def primary_route(self) -> str:
        return self.clients[0][0]

    def complete(self, request: LLMRequest) -> LLMResponse:
        attempts = 0
        last: LLMError | None = None

        for hop, (route, client) in enumerate(self.clients):
            for attempt in range(1, self.max_attempts + 1):
                attempts += 1
                try:
                    response = client.complete(request)
                    response.attempts = attempts
                    self._record(route, hop, attempt, "ok", None)
                    return response
                except LLMError as exc:
                    last = exc
                    self._record(route, hop, attempt, "error", exc)
                    if not exc.retryable:
                        break  # not worth retrying — hop instead
                    if attempt < self.max_attempts:
                        delay = exc.retry_after or self.base_backoff_s * (2 ** (attempt - 1))
                        self._record(route, hop, attempt, "backoff", None, delay=delay)
                        self._sleep(delay)
            if hop + 1 < len(self.clients):
                self._record(self.clients[hop + 1][0], hop + 1, 0, "fallback", None)

        raise last or LLMError("every route failed with no error recorded")

    def _record(self, route, hop, attempt, event, exc, delay=None) -> None:
        entry = {
            "route": route,
            "hop": hop,
            "attempt": attempt,
            "event": event,
            "status": getattr(exc, "status", None),
            "detail": str(exc) if exc else "",
            "delay_s": delay,
        }
        self.transcript.append(entry)
        fields = {k: v for k, v in entry.items() if k != "event" and v not in (None, "")}
        log.info("llm_" + event, **fields)

    def format_transcript(self) -> str:
        lines = []
        for e in self.transcript:
            if e["event"] == "ok":
                lines.append(f"  [{e['route']}] attempt {e['attempt']} -> 200 OK")
            elif e["event"] == "error":
                lines.append(f"  [{e['route']}] attempt {e['attempt']} -> {e['status']} {e['detail'][:54]}")
            elif e["event"] == "backoff":
                lines.append(f"  [{e['route']}] backing off {e['delay_s']:.2f}s (Retry-After honoured)")
            elif e["event"] == "fallback":
                lines.append(f"  --- primary exhausted, falling back to [{e['route']}] ---")
        return "\n".join(lines)

    def reset_transcript(self) -> None:
        self.transcript.clear()
