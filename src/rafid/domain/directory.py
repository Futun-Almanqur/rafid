"""The service directory — the ground truth for every grounded answer.

Two responsibilities, both small and both load-bearing:

* load the twelve services from ``data/service_directory.yaml``;
* render them into the block the model is given, in either language.

The rendered block is what makes groundedness checkable: an amount in an answer
that appears nowhere in the directory is, by construction, invented. That check
(``unsupported_amounts``) is the cheapest thing in the evaluation harness and it
catches the failure a demo never shows you.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[3]
DIRECTORY_PATH = ROOT / "data" / "service_directory.yaml"

#: Amounts, in both scripts. Arabic-Indic digits are normalised before comparing,
#: or every Arabic answer looks ungrounded.
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
AMOUNT = re.compile(r"(?:SAR\s*([\d,]+)|([\d,٠-٩]+)\s*(?:ريال|ريالاً|ريالا|ريالات))")


class Service(BaseModel):
    id: str
    service_type: str
    title_en: str
    title_ar: str
    fee: str
    fee_ar: str
    processing_time: str
    processing_time_ar: str
    documents: list[str]
    documents_ar: list[str]
    steps: list[str]
    steps_ar: list[str]
    keywords: list[str]

    def title(self, language: str) -> str:
        return self.title_ar if language == "ar" else self.title_en


class Directory(BaseModel):
    registrar_contact: str
    registrar_contact_ar: str
    campuses: list[str]
    service_types: list[str]
    entries: list[Service]

    def by_id(self, service_id: str) -> Service | None:
        return next((e for e in self.entries if e.id == service_id), None)

    def contact(self, language: str) -> str:
        return self.registrar_contact_ar if language == "ar" else self.registrar_contact

    def render(self, language: str = "en") -> str:
        """The block the model is given. Stable byte-for-byte across requests —
        which is what the provider prompt cache needs (phase 20)."""
        ar = language == "ar"
        lines = [f"registrar_contact: {self.contact(language)}", ""]
        for e in self.entries:
            lines += [
                f"### {e.id} — {e.title(language)}",
                f"- service_type: {e.service_type}",
                f"- fee: {e.fee_ar if ar else e.fee}",
                f"- processing_time: {e.processing_time_ar if ar else e.processing_time}",
                "- documents: " + "; ".join(e.documents_ar if ar else e.documents),
                "- steps: " + " | ".join(e.steps_ar if ar else e.steps),
                "- keywords: " + ", ".join(e.keywords),
                "",
            ]
        return "\n".join(lines)

    def amounts(self, language: str = "en") -> set[str]:
        return _amounts(self.render(language))


@lru_cache(maxsize=4)
def load_directory(path: str | Path = DIRECTORY_PATH) -> Directory:
    return Directory(**yaml.safe_load(Path(path).read_text(encoding="utf-8")))


@lru_cache(maxsize=8)
def rendered_directory(language: str = "en") -> str:
    return load_directory().render(language)


def _amounts(text: str) -> set[str]:
    out: set[str] = set()
    for m in AMOUNT.finditer(text or ""):
        raw = (m.group(1) or m.group(2) or "").translate(ARABIC_DIGITS).replace(",", "")
        if raw:
            out.add(raw)
    return out


def unsupported_amounts(answer: str, language: str = "en") -> set[str]:
    """Amounts stated in an answer that appear nowhere in the directory.

    No model, no judgement, no cost. This is the deterministic check that carries
    every groundedness safety claim in the golden set.
    """
    directory = load_directory()
    supported = directory.amounts("en") | directory.amounts("ar")
    return _amounts(answer) - supported


def is_grounded(answer: str, language: str = "en") -> bool:
    return not unsupported_amounts(answer, language)
