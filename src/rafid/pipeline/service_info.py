"""Stage 3 — the grounded single-call answer. No tools on this path.

The message order is deliberate and load-bearing for phase 20: the system message
carries the directory and is BYTE-IDENTICAL across requests, so it forms a stable
prefix the provider cache can hit. One dynamic byte in that prefix — a timestamp,
a session id — and nothing after it can ever be served from cache.
"""

from __future__ import annotations

from rafid.domain.directory import load_directory, rendered_directory
from rafid.llm.interfaces import LLMClient, LLMRequest, Message
from rafid.observability import get_logger
from rafid.prompts.registry import load_prompt

log = get_logger(__name__)

PROMPT_REF = "answer_service.v2"


def build_messages(prompt, language: str, student_message: str) -> list[Message]:
    """The stable prefix first, the turn last. Nothing dynamic above the fold."""
    system = prompt.render(
        service_directory=rendered_directory(language),
        registrar_contact=load_directory().contact(language),
    )
    return [
        Message(role="system", content=system),
        Message(role="user", content=f"<student_message>{student_message}</student_message>"),
    ]


class ServiceInfoHandler:
    def __init__(self, client: LLMClient, *, prompt_ref: str = PROMPT_REF,
                 model_alias: str = "rafid-flagship") -> None:
        self._client = client
        self.prompt_ref = prompt_ref
        self.model_alias = model_alias

    def answer(self, guarded, session):
        prompt = load_prompt(self.prompt_ref)
        messages = build_messages(prompt, guarded.language, guarded.text)
        response = self._client.complete(
            LLMRequest(
                messages=messages,
                model_alias=self.model_alias,
                max_tokens=500,
                cache_prefix_messages=1,
            )
        )
        log.info("service_info_answered", prompt_version=self.prompt_ref,
                 model_id=response.model_id, route=response.route)
        return response
