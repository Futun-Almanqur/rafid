"""Structured extraction: validate -> retry -> repair, bounded and measured.

One repair, not an unbounded loop, and repair is not magic: a share of cases stay
broken, which is what puts the escalation path on the corpus report instead of
only in the design document.

The repair turn re-reads the ORIGINAL message, never the validation feedback.
Extracting from the error message produces a request object about the error —
complete with a campus lifted out of the enum listed in the error. That one line
is the whole difference.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from rafid.domain.directory import rendered_directory
from rafid.domain.request import StudentRequest
from rafid.llm.interfaces import LLMClient, LLMRequest, Message
from rafid.observability import get_logger
from rafid.prompts.registry import load_prompt

log = get_logger(__name__)

PROMPT_REF = "extract_request.v1"


class ExtractionResult:
    def __init__(self) -> None:
        self.request: StudentRequest | None = None
        self.attempts: int = 0
        self.repaired: bool = False
        self.error: str = ""

    @property
    def ok(self) -> bool:
        return self.request is not None


def extract_request(
    client: LLMClient, message: str, *, language: str = "en", model_alias: str = "rafid-extract"
) -> ExtractionResult:
    prompt = load_prompt(PROMPT_REF)
    system = prompt.render(service_directory=rendered_directory(language))
    out = ExtractionResult()

    for attempt in (1, 2):
        out.attempts = attempt
        messages = [
            Message(role="system", content=system),
            Message(role="user", content=f"<student_message>{message}</student_message>"),
        ]
        if attempt == 2:
            # The repair turn re-reads the ORIGINAL message. The feedback is a
            # separate instruction, never the thing being extracted from.
            messages.append(
                Message(role="user", content=f"The previous output failed validation: {out.error}")
            )

        response = client.complete(
            LLMRequest(
                messages=messages,
                model_alias=model_alias,
                max_tokens=400,
                response_format=StudentRequest.json_schema_for_provider(),
                cache_prefix_messages=1,
            )
        )
        try:
            payload = json.loads(response.text or "{}")
            out.request = StudentRequest(**payload)
            out.repaired = attempt == 2
            log.info("extract_ok", attempts=attempt, repaired=out.repaired,
                     prompt_version=PROMPT_REF)
            return out
        except (json.JSONDecodeError, ValidationError) as exc:
            out.error = str(exc)[:300]
            log.warning("extract_failed", attempt=attempt, error=out.error[:120])

    return out
