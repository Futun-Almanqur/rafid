"""Stage 2 — intent routing. One cheap call, three destinations.

Router-first is the pattern: classify once, then send the turn down the cheapest
path that can answer it. An FAQ that costs a tool loop is a router that isn't
doing its job.

The deliberate fallback matters. A router that cannot decide sends the turn to
`service_info` — the grounded, read-only path — because guessing towards the path
that can ACT is the expensive mistake.
"""

from __future__ import annotations

from rafid.llm.interfaces import LLMClient, LLMRequest, Message
from rafid.observability import get_logger
from rafid.prompts.registry import load_prompt

log = get_logger(__name__)

INTENTS = ("service_info", "my_request", "escalate")
PROMPT_REF = "route_intent.v1"

#: A structured verdict, not free prose. Naming the schema is also what tells a
#: provider (and our gateway) that this is a classification call, not generation.
ROUTE_VERDICT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "route_verdict",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"intent": {"type": "string", "enum": list(INTENTS)}},
            "required": ["intent"],
            "additionalProperties": False,
        },
    },
}


class IntentRouter:
    def __init__(self, client: LLMClient, *, model_alias: str = "rafid-router") -> None:
        self._client = client
        self.model_alias = model_alias

    def classify(self, text: str) -> str:
        prompt = load_prompt(PROMPT_REF)
        response = self._client.complete(
            LLMRequest(
                messages=[
                    Message(role="system", content=prompt.render()),
                    Message(role="user", content=f"<student_message>{text}</student_message>"),
                ],
                model_alias=self.model_alias,
                max_tokens=8,
                response_format=ROUTE_VERDICT_SCHEMA,
                cache_prefix_messages=1,
            )
        )
        word = (response.text or "").strip().lower().split()[0] if response.text else ""
        word = word.strip(".,:;\"'")
        if word not in INTENTS:
            log.warning("router_fallback", got=word[:20])
            return "service_info"  # the cheap, read-only path
        log.info("routed", intent=word, prompt_version=PROMPT_REF)
        return word
