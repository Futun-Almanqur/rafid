"""ADAPTER SECTION — Anthropic Messages-dialect wire client.

`POST /v1/messages`. Four differences from the other dialect, all of them in this
file and none of them above the boundary:

  * the system prompt is a top-level field, not a message with role "system";
  * `max_tokens` is required by the API, not merely advisable;
  * content is a list of typed blocks rather than a string;
  * it says `stop_reason`, and reports cache reads as `cache_read_input_tokens`.

Every one of those is a reason the boundary exists. Application code that had to
know which of the two it was talking to would have the dialect smeared through it.
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


class AnthropicCompatClient:
    """Speaks `POST {base_url}/v1/messages`."""

    dialect = "anthropic"

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
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            transport=transport,
        )

    def resolve(self, alias: str) -> str:
        return self._aliases.get(alias, self._aliases.get("rafid-default", alias))

    def complete(self, request: LLMRequest) -> LLMResponse:
        model = self.resolve(request.model_alias)

        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        turns = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role in ("user", "assistant")
        ]
        payload: dict = {
            "model": model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": turns or [{"role": "user", "content": ""}],
        }
        if system:
            payload["system"] = system
        if request.tools:
            payload["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {}),
                }
                for t in request.tools
            ]

        started = time.perf_counter()
        try:
            r = self._client.post(f"{self.base_url}/v1/messages", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMError("request timed out", status=408, retryable=True, route=self.route) from exc
        except httpx.HTTPError as exc:
            raise LLMError(str(exc), status=None, retryable=True, route=self.route) from exc
        latency_ms = (time.perf_counter() - started) * 1000

        if r.status_code >= 400:
            raise self._error(r)

        data = r.json()
        blocks = data.get("content", []) or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text") or None
        usage = data.get("usage", {}) or {}

        return LLMResponse(
            text=text,
            tool_calls=[
                ToolCall(
                    id=b.get("id", ""),
                    name=b.get("name", ""),
                    arguments=json.dumps(b.get("input", {}), ensure_ascii=False),
                )
                for b in blocks
                if b.get("type") == "tool_use"
            ],
            finish_reason=self._finish(data.get("stop_reason")),
            model_id=data.get("model", model),
            usage=Usage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cached_input_tokens=usage.get("cache_read_input_tokens", 0),
            ),
            latency_ms=latency_ms,
            route=self.route,
        )

    @staticmethod
    def _finish(reason: str | None) -> str:
        return {
            "end_turn": "stop",
            "max_tokens": "length",
            "tool_use": "tool_calls",
            "stop_sequence": "stop",
            "refusal": "refusal",
        }.get(reason or "end_turn", "stop")

    def _error(self, r: httpx.Response) -> LLMError:
        try:
            message = r.json().get("error", {}).get("message", r.text[:200])
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
