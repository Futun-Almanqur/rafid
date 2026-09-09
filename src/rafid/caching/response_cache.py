"""Two-tier response cache. The exact tier is safe and boring. The semantic tier
is a quality trade, and it is treated with the suspicion a quality trade deserves.

Keys carry everything that could change the answer — model, prompt version, the
rendered prompt, the sampling parameters, the language, the intent. A key that
omits the prompt version serves yesterday's behaviour after today's deploy.

The semantic tier is scoped by language AND intent, and **only impersonal content
is ever eligible**. Anything conditioned on session state is excluded by
construction rather than by a condition someone might later edit — that is the
difference between a cost optimisation and a data-protection incident.

Two numbers, always reported together: hit rate AND wrong-hit rate. The pairing
rule from the guards has an exact analogue here. A 40% hit rate with one wrong hit
per thousand is not a saving for a university assistant.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field

from rafid.observability import get_logger

log = get_logger(__name__)


@dataclass
class CacheScope:
    """What makes two questions the same question."""

    language: str = "en"
    intent: str = "service_info"
    #: The whole safety argument in one flag. Personalised content is never
    #: semantically cacheable — not "usually not", never.
    personalised: bool = True

    @property
    def semantic_eligible(self) -> bool:
        return not self.personalised and self.intent == "service_info"

    @property
    def name(self) -> str:
        return f"{self.intent}:{self.language}:{'personal' if self.personalised else 'impersonal'}"


def exact_key(*, model_id: str, prompt_ref: str, rendered_prompt: str,
              question: str, temperature: float, max_tokens: int, scope: CacheScope) -> str:
    """Everything that could change the answer goes in the key. Nothing else does."""
    material = json.dumps({
        "model_id": model_id,
        "prompt_ref": prompt_ref,                 # <- the one most often forgotten
        "prompt_sha": hashlib.sha256(rendered_prompt.encode()).hexdigest()[:16],
        "question": question.strip().lower(),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "language": scope.language,
        "intent": scope.intent,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode()).hexdigest()


# --- the embedding stand-in -------------------------------------------------
# A bag-of-folded-tokens cosine. Deliberately simple and offline: what the module
# is teaching is the THRESHOLD DISCIPLINE and the wrong-hit suite, not the encoder.
# A real deployment swaps this for a sentence embedder; nothing else changes.
_AR_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ـ": ""})
_STOP = {"the", "a", "an", "is", "for", "of", "to", "my", "i", "do", "how", "what",
         "much", "does", "cost", "في", "من", "على", "هل", "ما", "كم"}


def _tokens(text: str) -> dict[str, int]:
    text = text.lower().translate(_AR_FOLD)
    out: dict[str, int] = {}
    for token in re.findall(r"\w+", text):
        if token not in _STOP:
            out[token] = out.get(token, 0) + 1
    return out


def cosine(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    shared = set(ta) & set(tb)
    num = sum(ta[t] * tb[t] for t in shared)
    den = math.sqrt(sum(v * v for v in ta.values())) * math.sqrt(sum(v * v for v in tb.values()))
    return num / den if den else 0.0


@dataclass
class ResponseCache:
    """Exact tier always; semantic tier only where it is provably safe."""

    semantic_enabled: bool = False
    semantic_threshold: float = 0.90
    exact: dict[str, tuple[str, str]] = field(default_factory=dict)   # key -> (question, answer)
    semantic: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # scope -> [(q, a)]
    hits_exact: int = 0
    hits_semantic: int = 0
    misses: int = 0

    def get(self, key: str, question: str, scope: CacheScope) -> tuple[str | None, str]:
        if key in self.exact:
            self.hits_exact += 1
            return self.exact[key][1], "exact"

        if self.semantic_enabled and scope.semantic_eligible:
            best, best_score = None, 0.0
            for cached_q, cached_a in self.semantic.get(scope.name, []):
                score = cosine(question, cached_q)
                if score > best_score:
                    best, best_score = cached_a, score
            if best is not None and best_score >= self.semantic_threshold:
                self.hits_semantic += 1
                log.info("semantic_cache_hit", score=round(best_score, 3), scope=scope.name)
                return best, "semantic"

        self.misses += 1
        return None, ""

    def put(self, key: str, question: str, answer: str, scope: CacheScope) -> None:
        self.exact[key] = (question, answer)
        if scope.semantic_eligible:
            self.semantic.setdefault(scope.name, []).append((question, answer))

    @property
    def hit_rate(self) -> float:
        total = self.hits_exact + self.hits_semantic + self.misses
        return (self.hits_exact + self.hits_semantic) / total if total else 0.0

    def stats(self) -> dict:
        return {
            "hits_exact": self.hits_exact,
            "hits_semantic": self.hits_semantic,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate, 4),
            "semantic_threshold": self.semantic_threshold,
        }
