"""ADAPTER SECTION — OpenAI-dialect client, built on the official OpenAI SDK.

**This file and its siblings in `src/rafid/llm/` are the only place in the
project allowed to import a provider SDK.** `tests/test_architecture.py` enforces
that, and carries a negative control so the check can actually fail.

`POST {base_url}/chat/completions`. Three very different things speak this
dialect: a commercial cloud API, our local gateway, and a vLLM server in front of
an open-weight checkpoint. The SDK is pointed at `base_url` from config, so all
three are the same code and the zero-key local path is unchanged.

What stays ABOVE the boundary, deliberately:

* **retry, backoff and the fallback hop** live in `ResilientClient`. The SDK's own
  retry is therefore disabled (`max_retries=0`) — two retry layers means a 429
  gets retried 3x2 times and the transcript stops meaning anything.
* **model aliases** are resolved here from config, so no caller ever names a
  concrete model.
* **errors** are normalised to `LLMError` with `retryable` set from the status,
  so nothing above this file catches an SDK exception type.
"""

from __future__ import annotations

import time

import openai  # the provider SDK — allowed HERE and nowhere else
from openai import OpenAI

from rafid.llm.interfaces import (
    RETRYABLE_STATUS,
    LLMError,
    LLMRequest,
    LLMResponse,
    ToolCall,
    Usage,
)

SDK_NAME = "openai"
SDK_VERSION = openai.__version__


class OpenAICompatClient:
    """Speaks the OpenAI chat-completions dialect, via the official SDK."""

    dialect = "openai"

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str = "not-needed",
        route: str = "",
        aliases: dict[str, str] | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.route = route
        self._aliases = aliases or {}
        #: max_retries=0 on purpose — see the module docstring. Reliability policy
        #: is ResilientClient's job, and having it in two places makes the drill
        #: transcripts unreadable and the backoff wrong.
        self._sdk = OpenAI(
            base_url=self.base_url,
            api_key=api_key or "not-needed",
            timeout=timeout,
            max_retries=0,
        )

    @property
    def sdk(self) -> OpenAI:
        """The live SDK client. Exposed for the architecture evidence cell."""
        return self._sdk

    def resolve(self, alias: str) -> str:
        return self._aliases.get(alias, self._aliases.get("rafid-default", alias))

    def complete(self, request: LLMRequest) -> LLMResponse:
        model = self.resolve(request.model_alias)
        kwargs: dict = {
            "model": model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [self._encode(m) for m in request.messages],
        }
        if request.tools:
            kwargs["tools"] = request.tools
        if request.response_format:
            kwargs["response_format"] = request.response_format

        started = time.perf_counter()
        try:
            completion = self._sdk.chat.completions.create(**kwargs)
        except openai.APIStatusError as exc:
            raise self._from_status(exc) from exc
        except openai.APITimeoutError as exc:
            raise LLMError("request timed out", status=408, retryable=True,
                           route=self.route) from exc
        except openai.APIConnectionError as exc:
            raise LLMError(str(exc), status=None, retryable=True, route=self.route) from exc
        latency_ms = (time.perf_counter() - started) * 1000

        choice = completion.choices[0]
        message = choice.message
        usage = completion.usage
        cached = 0
        if usage is not None and getattr(usage, "prompt_tokens_details", None) is not None:
            cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0

        return LLMResponse(
            text=message.content,
            tool_calls=[
                ToolCall(id=tc.id or "", name=tc.function.name,
                         arguments=tc.function.arguments or "{}")
                for tc in (message.tool_calls or [])
            ],
            finish_reason=self._finish(choice.finish_reason),
            model_id=completion.model or model,
            usage=Usage(
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                cached_input_tokens=cached,
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
                {"id": t.id, "type": "function",
                 "function": {"name": t.name, "arguments": t.arguments}}
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

    def _from_status(self, exc: openai.APIStatusError) -> LLMError:
        """Normalise an SDK exception into our one error type.

        Nothing above this file may catch an `openai.*` exception — that would be
        the SDK leaking across the boundary by a different door.
        """
        status = exc.status_code
        retry_after = None
        try:
            raw = exc.response.headers.get("retry-after")
            retry_after = float(raw) if raw else None
        except Exception:  # noqa: BLE001 - headers are best-effort
            retry_after = None
        message = str(getattr(exc, "message", "") or exc)[:200]
        return LLMError(
            message,
            status=status,
            retryable=status in RETRYABLE_STATUS,
            retry_after=retry_after,
            route=self.route,
        )
