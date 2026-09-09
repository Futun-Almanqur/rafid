r"""The model boundary. Application code imports THIS — never a provider SDK.

Everything above this line is provider-neutral: one request type, one response
type, one error type. The adapters below it (``openai_compat``, ``anthropic_compat``,
``fake``) are the only files allowed to know a wire dialect exists.

The rule that keeps it honest, enforced by ``tests/test_architecture.py``::

    no module outside src/rafid/llm/ may import a provider SDK
    every LLMRequest must bound max_tokens
    no prompt text may live in Python source

A boundary nothing checks is a convention, and conventions decay.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

FinishReason = Literal["stop", "length", "tool_calls", "refusal", "error"]


class ToolCall(BaseModel):
    """A tool the model wants the *application* to run. The model never runs it."""

    id: str = ""
    name: str
    arguments: str = "{}"  # raw JSON string; parsed and validated at the tool gate


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class LLMRequest(BaseModel):
    """max_tokens has no default on purpose — see test_every_llm_request_bounds_max_tokens."""

    messages: list[Message]
    model_alias: str = "rafid-default"  # resolved via config, never a literal model id
    max_tokens: int = Field(..., gt=0)  # ALWAYS bounded, always explicit
    temperature: float = Field(0.2, ge=0.0, le=2.0)
    tools: list[dict] | None = None  # provider-neutral JSON schema
    response_format: dict | None = None
    cache_prefix_messages: int = 0  # how many leading messages form the stable prefix


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0


class LLMResponse(BaseModel):
    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: FinishReason = "stop"
    model_id: str = ""  # the CONCRETE model that answered, never the alias
    usage: Usage = Field(default_factory=Usage)
    latency_ms: float = 0.0
    route: str = ""  # which configured route served it
    attempts: int = 1  # how many tries it took (ResilientClient fills this in)


@runtime_checkable
class LLMClient(Protocol):
    """Everything the application is allowed to know about a model provider."""

    def complete(self, request: LLMRequest) -> LLMResponse: ...


class LLMError(RuntimeError):
    """Normalised provider failure. ``retryable`` drives the retry policy."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
        route: str = "",
        raw: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after
        self.route = route
        self.raw = raw

    def __repr__(self) -> str:  # pragma: no cover - debugging affordance
        return f"LLMError(status={self.status}, retryable={self.retryable}, msg={self!s})"


#: Which HTTP statuses are worth trying again. 400 is not: three times the bug,
#: three times the cost.
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
