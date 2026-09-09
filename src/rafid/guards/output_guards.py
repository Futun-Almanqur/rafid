"""The outbound wall. Three checks, none of them a model call.

* **the canary** — planted in every rendered system prompt. If it appears in a
  response, the prompt leaked, and the response never reaches the student.
* **identifiers** — nothing unmasked leaves the system, including identifiers the
  model reconstructed rather than echoed.
* **groundedness** — an amount that appears nowhere in the directory is invented
  by construction. This is the cheapest check in the project and it catches the
  failure a demo never shows you.
"""

from __future__ import annotations

from pydantic import BaseModel

from rafid.domain.directory import unsupported_amounts
from rafid.domain.session import PII_PATTERNS, REFERENCE_PATTERNS
from rafid.guards.refusals import refusal_for
from rafid.observability import get_logger
from rafid.prompts.registry import CANARY

log = get_logger(__name__)


class OutputVerdict(BaseModel):
    allowed: bool = True
    category: str = ""
    detail: str = ""


def _own_confirmations(session) -> set[str]:
    """References this session created in this conversation."""
    return {
        r.get("confirmation")
        for r in getattr(session, "completed_side_effects", {}).values()
        if isinstance(r, dict) and r.get("confirmation")
    }


class OutputGuard:
    def __init__(self, *, check_grounding: bool = True) -> None:
        self.check_grounding = check_grounding

    def apply(self, text: str, *, language: str = "en", session=None) -> tuple[str, OutputVerdict]:
        if not text:
            return text, OutputVerdict(allowed=True)

        if CANARY in text:
            log.error("canary_leak_blocked")
            return (
                refusal_for("system_prompt_leak", language),
                OutputVerdict(allowed=False, category="system_prompt_leak"),
            )

        # PII never leaves, whoever it belongs to.
        for kind, pattern in PII_PATTERNS.items():
            if pattern.search(text):
                log.warning("identifier_outbound_blocked", kind=kind)
                return (
                    refusal_for("identifier_outbound", language),
                    OutputVerdict(allowed=False, category="identifier_outbound", detail=kind),
                )

        # A case reference leaves only if this session owns it. A confirmation the
        # student just created is theirs; someone else's request number is not.
        for kind, pattern in REFERENCE_PATTERNS.items():
            for match in pattern.finditer(text):
                ref = match.group()
                owned = session is None or session.owns(ref) or ref in _own_confirmations(session)
                if not owned:
                    log.warning("foreign_reference_blocked", kind=kind)
                    return (
                        refusal_for("identifier_outbound", language),
                        OutputVerdict(allowed=False, category="foreign_reference", detail=kind),
                    )

        if self.check_grounding:
            invented = unsupported_amounts(text, language)
            if invented:
                log.warning("ungrounded_amount", amounts=sorted(invented))
                return text, OutputVerdict(
                    allowed=True, category="ungrounded_amount", detail=",".join(sorted(invented))
                )

        return text, OutputVerdict(allowed=True)
