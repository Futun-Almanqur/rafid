"""ADAPTER SECTION — FakeClient: a scripted client for tests and drills.

Two jobs:

  * make tests deterministic and free — every stage test constructs one of these
    in three lines and asserts on what the stage did with the answer;
  * make failure *scripted*. A fault that only happens when a provider is having
    a bad day cannot be demonstrated on demand, and a fallback chain nobody has
    ever seen fire is a chain nobody knows works.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from rafid.llm.interfaces import LLMError, LLMRequest, LLMResponse, ToolCall, Usage


class FakeClient:
    """Scripted responses and scripted failures, in order."""

    dialect = "fake"

    def __init__(self, *, route: str = "fake", model_id: str = "fake-model") -> None:
        self.route = route
        self.model_id = model_id
        self._script: list[Callable[[LLMRequest], LLMResponse]] = []
        self.calls: list[LLMRequest] = []

    # -- scripting ---------------------------------------------------------
    def script_text(self, text: str, *, finish: str = "stop") -> FakeClient:
        self._script.append(
            lambda _r: LLMResponse(
                text=text,
                finish_reason=finish,
                model_id=self.model_id,
                route=self.route,
                usage=Usage(input_tokens=100, output_tokens=max(1, len(text) // 4)),
            )
        )
        return self

    def script_tool_call(self, name: str, arguments: dict) -> FakeClient:
        self._script.append(
            lambda _r: LLMResponse(
                tool_calls=[
                    ToolCall(id=f"call_{len(self.calls)}", name=name, arguments=json.dumps(arguments))
                ],
                finish_reason="tool_calls",
                model_id=self.model_id,
                route=self.route,
                usage=Usage(input_tokens=100, output_tokens=20),
            )
        )
        return self

    def script_error(
        self, *, status: int = 429, retryable: bool = True, retry_after: float | None = None
    ) -> FakeClient:
        def _raise(_r: LLMRequest) -> LLMResponse:
            raise LLMError(
                f"scripted {status}",
                status=status,
                retryable=retryable,
                retry_after=retry_after,
                route=self.route,
            )

        self._script.append(_raise)
        return self

    def script_errors(self, count: int, **kwargs) -> FakeClient:
        for _ in range(count):
            self.script_error(**kwargs)
        return self

    def always(self, fn: Callable[[LLMRequest], LLMResponse]) -> FakeClient:
        self._always = fn
        return self

    # -- the boundary ------------------------------------------------------
    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        started = time.perf_counter()
        if self._script:
            response = self._script.pop(0)(request)
        elif getattr(self, "_always", None):
            response = self._always(request)
        else:
            response = LLMResponse(
                text="(fake) nothing scripted",
                model_id=self.model_id,
                route=self.route,
                usage=Usage(input_tokens=10, output_tokens=5),
            )
        response.latency_ms = (time.perf_counter() - started) * 1000
        return response
