"""ADAPTER SECTION — OpenAI-dialect wire client. One of two dialect adapters.

`POST /v1/chat/completions`. Three very different things speak this dialect: a
commercial cloud API, the local gateway, and a vLLM server in front of an
open-weight checkpoint. That is exactly why the route is configuration and not
code — the same adapter serves all three, and swapping one for another is a
`base_url` change.

WHY httpx AND NOT THE VENDOR SDK. The SDK buys retries and typed models we
already have above the boundary, and costs a dependency whose surface changes
between minor versions. The wire contract does not change. `tests/
test_architecture.py` still forbids importing `openai` or `anthropic` anywhere
outside this directory, and proves that check can fail with a negative control —
see ADR 005.
"""

from __future__ import annotations

import json
import time

import httpx

from rafid.llm.interfaces import (
    RETRYABLE_STATUS,
    LLMError,
    LLMRequest,
    LLMResponse,
    ToolCall,
    Usage,
)


class OpenAICompatClient:
    """Speaks `POST {base_url}/chat/completions`."""

    dialect = "openai"

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "not-needed",
        route: str = "",
        aliases: dict[str, str] | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.route = route
        self._aliases = aliases or {}
        self._client = httpx.Client(
            timeout=timeout,
            headers={"authorization": f"Bearer {api_key}", "content-type": "application/json"},
            transport=transport,
        )

    def resolve(self, alias: str) -> str:
        return self._aliases.get(alias, self._aliases.get("rafid-default", alias))

    def complete(self, request: LLMRequest) -> LLMResponse:
        model = self.resolve(request.model_alias)
        payload: dict = {
            "model": model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [self._encode(m) for m in request.messages],
        }
        if request.tools:
            payload["tools"] = request.tools
        if request.response_format:
            payload["response_format"] = request.response_format

        started = time.perf_counter()
        try:
            r = self._client.post(f"{self.base_url}/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMError("request timed out", status=408, retryable=True, route=self.route) from exc
        except httpx.HTTPError as exc:
            raise LLMError(str(exc), status=None, retryable=True, route=self.route) from exc
        latency_ms = (time.perf_counter() - started) * 1000

        if r.status_code >= 400:
            raise self._error(r)

        data = r.json()
        choice = data["choices"][0]
        message = choice.get("message", {})
        usage = data.get("usage", {}) or {}
        details = usage.get("prompt_tokens_details", {}) or {}

        return LLMResponse(
            text=message.get("content"),
            tool_calls=[
                ToolCall(
                    id=tc.get("id", ""),
                    name=tc["function"]["name"],
                    arguments=tc["function"].get("arguments", "{}"),
                )
                for tc in (message.get("tool_calls") or [])
            ],
            finish_reason=self._finish(choice.get("finish_reason")),
            model_id=data.get("model", model),
            usage=Usage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                cached_input_tokens=details.get("cached_tokens", 0),
            ),
            latency_ms=latency_ms,
            route=self.route,
        )

    # -- wire details ------------------------------------------------------
    @staticmethod
    def _encode(m) -> dict:
        out: dict = {"role": m.role, "content": m.content}
        if m.tool_call_id:
            out["tool_call_id"] = m.tool_call_id
        if m.name:
            out["name"] = m.name
        if m.tool_calls:
            out["tool_calls"] = [
                {"id": t.id, "type": "function", "function": {"name": t.name, "arguments": t.arguments}}
                for t in m.tool_calls
            ]
        return out

    @staticmethod
    def _finish(reason: str | None) -> str:
        return {
            "stop": "stop",
            "length": "length",
            "tool_calls": "tool_calls",
            "content_filter": "refusal",
        }.get(reason or "stop", "stop")

    def _error(self, r: httpx.Response) -> LLMError:
        try:
            body = r.json().get("error", {})
            message = body.get("message", r.text[:200])
        except json.JSONDecodeError:
            message = r.text[:200]
        retry_after = r.headers.get("retry-after")
        return LLMError(
            message,
            status=r.status_code,
            retryable=r.status_code in RETRYABLE_STATUS,
            retry_after=float(retry_after) if retry_after else None,
            route=self.route,
        )
