"""What flows out of the pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Reply(BaseModel):
    text: str = ""
    intent: str = "service_info"
    language: str = "en"
    blocked: bool = False
    escalated: bool = False
    guard_layer: str = ""
    guard_category: str = ""
    output_guard_category: str = ""
    tool_calls: list[dict] = Field(default_factory=list)
    model_id: str = ""
    route: str = ""
    prompt_version: str = ""
    latency_ms: float = 0.0
    stages: list[str] = Field(default_factory=list)
