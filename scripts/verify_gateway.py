"""Phase 1 verification — does the adapted gateway actually work, and is it ours?

    python scripts/verify_gateway.py

It drives the gateway's ASGI application in-process with Starlette's TestClient:
the same app object, the same routes, real request/response cycles, no port to
manage. Phase 2 will additionally exercise it over a real socket, because that is
what the Colab setup cell does.

Four checks, all against a running gateway:

  1. OpenAI dialect   — POST /v1/chat/completions responds with usage accounting
  2. Anthropic dialect — POST /v1/messages responds with its own frame shape
  3. A grounded Wadi answer — the fee in the reply comes from OUR directory
  4. Refusal off-directory — a service we do not offer produces a refusal, not
     an invented fee. This is what proves check 3 was grounding and not luck.

SCOPE NOTE. The directory renderer and the instruction string below are a
throwaway verification harness, not project artefacts. The domain module that
renders the directory properly is phase 6; the versioned prompt artefacts are
phase 7. Nothing here is imported by application code, because there is no
application code yet.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
DIRECTORY = ROOT / "data" / "service_directory.yaml"

sys.path.insert(0, str(ROOT / "gateway"))

# --- environment workaround, NOT part of the project -------------------------
# The gateway counts tokens with tiktoken, which downloads its BPE table on first
# use. That download is blocked in this sandbox (the proxy denies
# openaipublic.blob.core.windows.net). Colab has open network and will fetch it
# normally, so this is an environment limitation, not a defect in the gateway.
#
# To let the rest of the verification run here, a byte-level stand-in encoder is
# installed BEFORE the gateway is imported — and only inside this script.
# Consequence, stated plainly: the token counts in the captured output below are
# the stand-in's, not tiktoken's. Everything else — routing, both wire dialects,
# grounding, the refusal — is unaffected, because none of it reads token counts.
TOKENIZER_IS_REAL = True
try:  # pragma: no cover - environment dependent
    import tiktoken

    tiktoken.get_encoding("o200k_base")
except Exception:  # noqa: BLE001
    TOKENIZER_IS_REAL = False
    import tiktoken

    class _ApproxEncoding:
        """~4 bytes per token. Enough to exercise the accounting path."""

        def encode(self, text: str) -> list[int]:
            data = (text or "").encode("utf-8")
            return list(range(max(1, len(data) // 4))) if data else []

        def decode(self, ids: list[int]) -> str:
            return "".join("x" for _ in ids)

    tiktoken.get_encoding = lambda *_a, **_k: _ApproxEncoding()  # type: ignore[assignment]
# -----------------------------------------------------------------------------

from app.main import app  # noqa: E402

client = TestClient(app)

# Throwaway. Phase 7 replaces this with a versioned artefact carrying a changelog.
INSTRUCTION = (
    "You are a student services assistant for Wadi University. Answer only from "
    "the service directory below. If the answer is not in the directory, say you "
    "do not know and point the student to the registrar."
)


def render_directory(language: str = "en") -> str:
    """Render the YAML into the block format the gateway parses out of a prompt."""
    spec = yaml.safe_load(DIRECTORY.read_text(encoding="utf-8"))
    ar = language == "ar"
    lines = [f"registrar_contact: {spec['registrar_contact_ar' if ar else 'registrar_contact']}", ""]
    for e in spec["entries"]:
        lines.append(f"### {e['id']} — {e['title_ar' if ar else 'title_en']}")
        lines.append(f"- service_type: {e['service_type']}")
        lines.append(f"- fee: {e['fee_ar' if ar else 'fee']}")
        lines.append(f"- processing_time: {e['processing_time_ar' if ar else 'processing_time']}")
        lines.append("- documents: " + "; ".join(e["documents_ar" if ar else "documents"]))
        lines.append("- steps: " + " | ".join(e["steps_ar" if ar else "steps"]))
        lines.append("- keywords: " + ", ".join(e["keywords"]))
        lines.append("")
    return "\n".join(lines)


def system_prompt(language: str = "en") -> str:
    return (
        f"{INSTRUCTION}\n\n"
        f"<service_directory>\n{render_directory(language)}\n</service_directory>"
    )


def ask_openai(question: str, language: str = "en", model: str = "course-flagship") -> dict:
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": model,
            "max_tokens": 400,
            "messages": [
                {"role": "system", "content": system_prompt(language)},
                {"role": "user", "content": f"<student_message>{question}</student_message>"},
            ],
        },
    )
    r.raise_for_status()
    return r.json()


def ask_anthropic(question: str, language: str = "en", model: str = "course-anthropic") -> dict:
    r = client.post(
        "/v1/messages",
        json={
            "model": model,
            "max_tokens": 400,
            "system": system_prompt(language),
            "messages": [
                {"role": "user", "content": f"<student_message>{question}</student_message>"}
            ],
        },
    )
    r.raise_for_status()
    return r.json()


def rule(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def main() -> int:
    failures: list[str] = []

    rule("environment")
    print(
        "tokenizer :",
        "tiktoken o200k_base (real)"
        if TOKENIZER_IS_REAL
        else "STAND-IN — tiktoken's BPE download is blocked in this sandbox; "
        "token counts below are approximate",
    )

    rule("0 · health and model listing")
    print("GET /healthz  ->", client.get("/healthz").json())
    models = client.get("/v1/models").json()
    ids = [m["id"] for m in models.get("data", [])]
    print("GET /v1/models ->", ids)
    if "wadi-onprem" not in ids:
        failures.append("the open-weight tier is not named wadi-onprem")
    if any("murshid" in i for i in ids):
        failures.append("a model id still carries the reference implementation's name")

    rule("1 · OpenAI dialect — POST /v1/chat/completions")
    data = ask_openai("How much does an official academic transcript cost?")
    text = data["choices"][0]["message"]["content"]
    print("model     :", data["model"])
    print("usage     :", json.dumps(data["usage"], ensure_ascii=False))
    print("finish    :", data["choices"][0]["finish_reason"])
    print("answer    :\n" + text)
    if "usage" not in data or not data["usage"].get("prompt_tokens"):
        failures.append("OpenAI dialect returned no usage accounting")

    rule("2 · Anthropic dialect — POST /v1/messages")
    a = ask_anthropic("How much does an official academic transcript cost?")
    a_text = "".join(b.get("text", "") for b in a.get("content", []))
    print("model     :", a.get("model"))
    print("usage     :", json.dumps(a.get("usage", {}), ensure_ascii=False))
    print("stop      :", a.get("stop_reason"))
    print("answer    :\n" + a_text)
    if not a_text:
        failures.append("Anthropic dialect returned no content")

    rule("3 · grounded in OUR directory — the fee must be SAR 60")
    if "SAR 60 per copy" in text:
        print("PASS  the OpenAI reply quotes 'SAR 60 per copy', which is the value in")
        print("      data/service_directory.yaml under transcript_request.")
    else:
        failures.append("the grounded answer did not quote our directory's fee")
        print("FAIL  expected 'SAR 60 per copy' in the reply")

    rule("3b · the same question in Arabic")
    ar = ask_openai("كم رسوم إصدار السجل الأكاديمي؟", language="ar")
    ar_text = ar["choices"][0]["message"]["content"]
    print(ar_text)
    if "٦٠" not in ar_text:
        failures.append("the Arabic grounded answer did not quote the directory fee")

    rule("4 · off-directory question must refuse, not invent")
    off = ask_openai("What is the fee for a falconry licence?")
    off_text = off["choices"][0]["message"]["content"]
    print(off_text)
    if "won't guess" in off_text or "I don't have that information" in off_text:
        print("\nPASS  refused instead of inventing a fee.")
    else:
        failures.append("an off-directory question produced an answer instead of a refusal")

    rule("verdict")
    if failures:
        print("FAILURES:")
        for f in failures:
            print("  -", f)
        return 1
    print("all phase-1 checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
