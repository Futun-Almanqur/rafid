"""The cascade: cheap-first, with a DETERMINISTIC escalation signal.

Why this exists, in order:

1. Routing FAQ traffic to the small model saved 96.7% of the bill.
2. The regression gate blocked it. Not on the average — on the slices: safety
   fell to 88%, Arabic fell 4 points, English 5.
3. The reflex is to hand back the saving. That treats the gate as an obstacle
   rather than as information. The gate had told us something specific: the small
   model is fine EXCEPT when it should be refusing. Its failures were all
   out-of-directory questions where it produced a plausible fee instead of "I
   don't know".

So: the small model answers. If the answer contains an amount that is not in the
service directory, the request is re-asked on the flagship. The escalation signal
is `unsupported_amounts` — **the same deterministic check the gate failed on**,
which means the cascade escalates on exactly the condition that blocked the
change.

The insurance premium is only paid on the turns that would have been wrong.
"""

from __future__ import annotations

from rafid.domain.directory import unsupported_amounts
from rafid.llm.interfaces import LLMClient, LLMRequest, LLMResponse
from rafid.observability import get_logger

log = get_logger(__name__)


class CascadeClient:
    """Cheap first; escalate to strong on an ungrounded amount.

    Implemented at the boundary rather than inside a handler, so every path that
    answers a student gets it and no call site has to remember.
    """

    def __init__(self, cheap: LLMClient, strong: LLMClient, *, language: str = "en") -> None:
        self._cheap = cheap
        self._strong = strong
        self.language = language
        self.escalations = 0
        self.calls = 0

    @property
    def dialect(self) -> str:
        return getattr(self._cheap, "dialect", "unknown")

    def resolve(self, alias: str) -> str:
        return self._cheap.resolve(alias)

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        response = self._cheap.complete(request)

        invented = unsupported_amounts(response.text or "", self.language)
        if invented:
            self.escalations += 1
            log.warning("cascade_escalated", amounts=sorted(invented),
                        from_model=response.model_id)
            response = self._strong.complete(request)
            response.route = f"{response.route}(cascade)"
        return response

    def stats(self) -> dict:
        return {
            "calls": self.calls,
            "escalations": self.escalations,
            "escalation_rate": round(self.escalations / self.calls, 4) if self.calls else 0.0,
        }
