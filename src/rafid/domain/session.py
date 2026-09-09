"""Conversation state, the identifier vault, and the authorisation gate.

The load-bearing idea: **authority lives here, not in the token stream.** Chat
history is data. Tool arguments are user input by proxy. Whether a booking may
happen — or whether a student may read a request — is decided here against the
*authenticated* student, never by anything a model said, however convincingly.

Authorisation is keyed on a tool's declared ``auth_policy``, never inferred from
its risk class. Risk class says what a tool does to the world; auth policy says
who may invoke it. Deriving one from the other is how a terminal escalation ends
up gated and a private read-only lookup ends up open — see ADR 006.

Every identifier here is fictional by construction: WU-STU-000123, WU-REQ-123456.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from rafid.llm.interfaces import Message
from rafid.observability import get_logger

log = get_logger(__name__)

#: Two kinds of identifier, treated differently on purpose.
#:
#: PII identifies a PERSON. It is masked inbound — before any model or log sees
#: it — and it may never leave the system in a reply.
PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\bWU-STU-\d{6}@students\.wadi\.example\b"),
    "student_id": re.compile(r"\bWU-STU-\d{6}\b"),
}

#: A REFERENCE identifies a CASE, not a person. It is opaque, it carries nothing
#: about the student, and the assistant is useless without it — a student asking
#: "where has WU-REQ-100045 got to?" needs it to reach the tool. So it is NOT
#: masked. What protects it is the authorisation gate: ownership is checked
#: against the authenticated session before anything is read, and a reference the
#: session does not own may not appear in a reply either.
#:
#: Masking it instead would have looked safer and been worse: it would have
#: disabled the lookup while leaving the real control — ownership — unchanged.
REFERENCE_PATTERNS: dict[str, re.Pattern[str]] = {
    "request_ref": re.compile(r"\bWU-REQ-\d{6}\b"),
    "appointment": re.compile(r"\bWU-APT-\d{6}\b"),
}

#: Everything the outbound wall knows how to recognise.
WADI_IDENTIFIERS: dict[str, re.Pattern[str]] = {**PII_PATTERNS, **REFERENCE_PATTERNS}

AuthPolicy = Literal["none", "session_owner", "session_owner_fresh"]


class IdentifierVault:
    """Session-scoped, reversible masking.

    The mask round-trips *inside* the trust boundary only: the booking flow needs
    the real value at the tool gate, and nothing outside this process ever does.
    """

    def __init__(self) -> None:
        self._by_token: dict[str, str] = {}
        self._by_value: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def store(self, kind: str, value: str) -> str:
        if value in self._by_value:
            return self._by_value[value]
        self._counters[kind] = self._counters.get(kind, 0) + 1
        token = f"⟦{kind.upper()}_{self._counters[kind]}⟧"
        self._by_token[token] = value
        self._by_value[value] = token
        return token

    def reveal(self, token: str) -> str | None:
        return self._by_token.get(token)

    def unmask(self, text: str) -> str:
        for token, value in self._by_token.items():
            text = text.replace(token, value)
        return text

    def __len__(self) -> int:
        return len(self._by_token)


class AuthorizationVerdict(BaseModel):
    allowed: bool
    reason: str = ""
    user_hint: str = ""


@dataclass
class ConversationState:
    """Windowed history: the last ``max_turns`` exchanges.

    Full history grows unboundedly — cost linear in turn number, then a
    context-length crash for your most engaged students first. Summarised history
    is the capstone extension we are not building. Windowed is what Rafid ships.
    """

    max_turns: int = 8
    turns: list[Message] = field(default_factory=list)

    def add_user(self, text: str) -> None:
        self.turns.append(Message(role="user", content=text))
        self._trim()

    def add_assistant(self, text: str) -> None:
        self.turns.append(Message(role="assistant", content=text))
        self._trim()

    def _trim(self) -> None:
        limit = self.max_turns * 2
        if len(self.turns) > limit:
            self.turns = self.turns[-limit:]

    def messages(self, system: str | None = None) -> list[Message]:
        head = [Message(role="system", content=system)] if system else []
        return head + list(self.turns)

    def clear(self) -> None:
        self.turns.clear()


class Session:
    """Everything the application knows that the conversation may not assert."""

    def __init__(
        self,
        student_id: str = "WU-STU-000123",
        *,
        identity_verified: bool = True,
        max_turns: int = 8,
        language: str = "en",
    ) -> None:
        self.id = f"sess_{uuid.uuid4().hex[:10]}"
        self.student_id = student_id
        self.language = language
        self.vault = IdentifierVault()
        self.state = ConversationState(max_turns=max_turns)
        self.identity_verified_at: datetime | None = (
            datetime.now(UTC) if identity_verified else None
        )
        self.verification_ttl = timedelta(minutes=15)
        #: Idempotency: a retried turn must not book twice.
        self.completed_side_effects: dict[str, dict] = {}
        self.tool_trace: list[dict] = []

    # --- identity ---------------------------------------------------------
    @property
    def identity_fresh(self) -> bool:
        if self.identity_verified_at is None:
            return False
        return datetime.now(UTC) - self.identity_verified_at <= self.verification_ttl

    def verify_identity(self) -> None:
        """Called by the *application* after an out-of-band check completes.

        Never called because a conversation claimed verification had happened.
        """
        self.identity_verified_at = datetime.now(UTC)

    def expire_identity(self) -> None:
        """Used by the safety tests to age a session past its TTL."""
        self.identity_verified_at = datetime.now(UTC) - self.verification_ttl * 2

    # --- ownership --------------------------------------------------------
    def owns(self, subject: str | None) -> bool:
        """Does the authenticated student own this subject?

        A subject arrives as either a student id (``WU-STU-``) or a request
        reference (``WU-REQ-``). A student id is compared directly; a reference is
        resolved to its owner. In a real deployment that resolution is a lookup
        against the student record system; here the fixture data in
        tools/services.py plays that part. Either way the DECISION is made here,
        against the authenticated session — never against what the model said.

        An unrecognised subject is not owned. Failing open on an identifier we
        cannot resolve would be the whole point, lost.
        """
        if subject is None:
            return True
        if subject.startswith("WU-STU-"):
            return subject == self.student_id
        from rafid.tools.services import owner_of_request

        owner = owner_of_request(subject)
        return owner is not None and owner == self.student_id

    # --- the gate ---------------------------------------------------------
    def idempotency_key(self, tool_name: str, args: dict) -> str:
        return "|".join([tool_name] + [f"{k}={args[k]}" for k in sorted(args)])

    def authorize(self, tool, args: dict) -> AuthorizationVerdict:
        """The single entry point. Dispatches on tool.auth_policy — nothing else.

        No branch here reads ``tool.risk``. That is the whole point of ADR 006.
        """
        policy: str = getattr(tool, "auth_policy", "none")
        name = getattr(tool, "name", str(tool))

        if policy == "none":
            return AuthorizationVerdict(allowed=True)

        if policy in ("session_owner", "session_owner_fresh"):
            if policy == "session_owner_fresh" and not self.identity_fresh:
                return AuthorizationVerdict(
                    allowed=False,
                    reason="identity_not_verified",
                    user_hint=(
                        "أحتاج إلى التحقق من هويتك قبل تنفيذ ذلك."
                        if self.language == "ar"
                        else "I need to verify your identity before I can do that."
                    ),
                )
            # The model's argument is user input by proxy. The session decides.
            subject = args.get("reference") or args.get("on_behalf_of") or args.get("student_id")
            if subject and not self.owns(subject):
                log.warning(
                    "authz_cross_student_denied",
                    session=self.id,
                    tool=name,
                    requested_for=subject,
                )
                return AuthorizationVerdict(
                    allowed=False,
                    reason="not_your_request" if args.get("reference") else "cross_student",
                    user_hint=(
                        "يمكنني الاطلاع على سجلك أنت فقط."
                        if self.language == "ar"
                        else "I can only look at your own records."
                    ),
                )
            if policy == "session_owner_fresh":
                key = self.idempotency_key(name, args)
                if key in self.completed_side_effects:
                    return AuthorizationVerdict(
                        allowed=False,
                        reason="already_done",
                        user_hint=(
                            "هذا محجوز بالفعل، ولن أكرره."
                            if self.language == "ar"
                            else "That is already booked — I won't book it twice."
                        ),
                    )
            return AuthorizationVerdict(allowed=True)

        raise ValueError(f"unknown auth_policy {policy!r} on tool {name!r}")

    def record_side_effect(self, tool_name: str, args: dict, result: dict) -> None:
        self.completed_side_effects[self.idempotency_key(tool_name, args)] = result


def mask_identifiers(text: str, session: Session) -> str:
    """Mask PII BEFORE any model or log sees the text.

    References are deliberately left alone — see REFERENCE_PATTERNS above.
    """
    for kind, pattern in PII_PATTERNS.items():
        for match in list(pattern.finditer(text)):
            token = session.vault.store(kind, match.group())
            text = text.replace(match.group(), token)
    return text


def contains_identifier(text: str) -> str | None:
    for kind, pattern in WADI_IDENTIFIERS.items():
        if pattern.search(text):
            return kind
    return None
