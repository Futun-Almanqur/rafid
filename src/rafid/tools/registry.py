"""Rafid's four tools. Three risk classes, three auth policies, all in code.

Tool schemas are prompts wearing a type system. The model chooses tools by
reading names and descriptions, so both are written for the model and reviewed
like prompts:

* **names** are verb_noun and unambiguous. A registry holding both
  ``check_status`` and ``get_status`` guarantees misrouting.
* **descriptions** say when to use the tool, when *not* to, and what it returns.
  A description that describes the API ("wrapper around the records endpoint")
  cannot route anything, and one that says "use for any question" fires on
  everything.
* **parameters** prefer enums to free strings wherever the domain is closed.

THREE INDEPENDENT FIELDS, and the reason they are independent (ADR 006):

  ``risk``        what this does to the world  -> logging, loop bounds, review
  ``visibility``  whose data it touches        -> a review invariant
  ``auth_policy`` who may invoke it            -> THE GATE READS ONLY THIS

Deriving authorisation from risk class is the bug ADR 006 records: it gates a
terminal escalation that needs no gate, and it leaves a private read-only lookup
open. ``check_my_request_status`` is the case that makes it concrete — read-only
does **not** mean unauthenticated.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from rafid.domain.directory import load_directory
from rafid.tools import services

RiskClass = Literal["read_only", "side_effecting", "terminal"]
Visibility = Literal["public", "private"]
AuthPolicy = Literal["none", "session_owner", "session_owner_fresh"]


class Tool(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    parameters: dict  # JSON Schema
    risk: RiskClass
    visibility: Visibility
    auth_policy: AuthPolicy
    fn: Callable  # executed by the APPLICATION, never by the model

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


SERVICE_IDS = [e.id for e in load_directory().entries]
CAMPUS_ENUM = load_directory().campuses
SLOT_ENUM = ["morning", "afternoon"]

TOOLS: list[Tool] = [
    Tool(
        name="lookup_service_information",
        risk="read_only",
        visibility="public",
        auth_policy="none",
        description=(
            "Look up what the university charges and how long it takes for one "
            "published campus service. Use when the student asks about a service in "
            "general — fees, processing time. Do NOT use to check the progress of a "
            "request the student has already submitted; that is "
            "check_my_request_status. Returns the fee and processing time."
        ),
        parameters={
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "enum": SERVICE_IDS,
                               "description": "The directory entry id."},
                "language": {"type": "string", "enum": ["en", "ar"]},
            },
            "required": ["service_id"],
            "additionalProperties": False,
        },
        fn=services.lookup_service_information,
    ),
    Tool(
        name="check_my_request_status",
        risk="read_only",
        visibility="private",  # <- read-only, but NOT public
        auth_policy="session_owner",
        description=(
            "Check the current status of a request the signed-in student has already "
            "submitted, by its reference (format: WU-REQ- followed by six digits). Use "
            "when the student asks about progress on their own request. Do NOT use for "
            "general fee questions, and do NOT use when no reference has been given — "
            "ask for it instead. Returns the status, when it last changed, and any note."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reference": {"type": "string", "pattern": "^WU-REQ-[0-9]{6}$"},
                "language": {"type": "string", "enum": ["en", "ar"]},
            },
            "required": ["reference"],
            "additionalProperties": False,
        },
        fn=services.check_my_request_status,
    ),
    Tool(
        name="book_advisor_appointment",
        risk="side_effecting",
        visibility="private",
        auth_policy="session_owner_fresh",
        description=(
            "Book an academic advisor appointment for the signed-in student. Use only "
            "after the student has given a campus, a date and a slot, and has confirmed. "
            "Do NOT use to check an existing appointment. Returns a confirmation "
            "reference."
        ),
        parameters={
            "type": "object",
            "properties": {
                "campus": {"type": "string", "enum": CAMPUS_ENUM},
                "date": {"type": "string", "pattern": "^20[0-9]{2}-[0-9]{2}-[0-9]{2}$"},
                "slot": {"type": "string", "enum": SLOT_ENUM},
                "on_behalf_of": {
                    "type": "string",
                    "description": (
                        "Ignored for authorisation. The session decides whose account "
                        "is acted on; this argument is user input by proxy."
                    ),
                },
            },
            "required": ["campus", "date", "slot"],
            "additionalProperties": False,
        },
        fn=services.book_advisor_appointment,
    ),
    Tool(
        name="escalate_to_registrar",
        risk="terminal",
        visibility="public",  # creates a hand-off for THIS conversation only
        auth_policy="none",
        description=(
            "Hand the conversation to a human in Admissions & Registration. Use when "
            "the student asks for a person, is making a complaint, or the question is "
            "outside what the service directory covers. Do NOT use for a question the "
            "service directory answers, and do NOT use to avoid looking something up. "
            "Ends the conversation turn. Returns a hand-off record."
        ),
        parameters={
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "One sentence for the human."},
                "reason": {
                    "type": "string",
                    "enum": ["student_request", "out_of_scope", "complaint", "distress"],
                },
            },
            "required": ["summary"],
            "additionalProperties": False,
        },
        fn=services.escalate_to_registrar,
    ),
]

BY_NAME: dict[str, Tool] = {t.name: t for t in TOOLS}


def by_name(name: str) -> Tool | None:
    return BY_NAME.get(name)


def schemas() -> list[dict]:
    return [t.schema() for t in TOOLS]
