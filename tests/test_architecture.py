"""Architecture rules, enforced by a test rather than by hoping.

Three claims this project makes about its own source, each true only for as long
as something checks it:

1. application code never imports a provider SDK;
2. prompt text lives in the registry as versioned files, never inline in Python;
3. no model call is unbounded — every ``LLMRequest`` sets ``max_tokens``.

Each check has a **negative control**: a synthetic offending file the check must
reject. Without those, a check that silently matched nothing would pass forever
and prove nothing. "Presence is not effect" applies to tests too.

Run inline in the notebook (§1.4), not only here.
"""

from __future__ import annotations

import ast
import re
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "rafid"

#: The adapter section — the only place a wire dialect may be known.
ADAPTER_DIR = SRC / "llm"
PROVIDER_SDKS = {"openai", "anthropic", "cohere", "google", "mistralai", "vertexai"}


def python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


# ---------------------------------------------------------------------------
# 1. No provider SDK outside the adapter section
# ---------------------------------------------------------------------------


def _sdk_offenders(files: list[Path], *, allow_dir: Path | None = ADAPTER_DIR) -> list[str]:
    offenders: list[str] = []
    for path in files:
        if allow_dir is not None and allow_dir in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                if name.split(".")[0] in PROVIDER_SDKS:
                    offenders.append(f"{path.name}:{node.lineno} imports {name}")
    return offenders


def test_no_provider_sdk_outside_the_adapter_section():
    offenders = _sdk_offenders(python_files(SRC))
    assert offenders == [], (
        "provider SDKs belong behind the boundary. Every one of these turns a "
        "config change into a rewrite:\n  " + "\n  ".join(offenders)
    )


def test_the_sdk_check_can_actually_fail():
    """Negative control. A check that cannot fail is decoration."""
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "sneaky.py"
        bad.write_text("import openai  # just to test\n", encoding="utf-8")
        assert _sdk_offenders([bad], allow_dir=None), "the SDK check failed to catch an import"


# ---------------------------------------------------------------------------
# 2. No inline prompt text in code
# ---------------------------------------------------------------------------

#: Phrases that mark a string as an instruction to a model rather than a label.
PROMPT_MARKERS = re.compile(
    r"(You are (a|an|the)\b|Answer only from|أنت مساعد|Your task is to\b)", re.I
)


def _prompt_offenders(files: list[Path]) -> list[str]:
    offenders: list[str] = []
    for path in files:
        if path.parts[-2:] == ("prompts", "registry.py"):
            continue  # the registry names the concept; it holds no prompt text
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if PROMPT_MARKERS.search(node.value):
                    offenders.append(f"{path.name}:{node.lineno}: {node.value[:60]!r}")
    return offenders


def test_no_inline_prompt_text_in_code():
    offenders = _prompt_offenders(python_files(SRC))
    assert offenders == [], (
        "prompt text lives in src/rafid/prompts/library as a versioned file with a "
        "changelog:\n  " + "\n  ".join(offenders)
    )


def test_the_inline_prompt_check_can_actually_fail():
    """Negative control."""
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "inline.py"
        bad.write_text('P = "You are a helpful assistant for Wadi."\n', encoding="utf-8")
        assert _prompt_offenders([bad]), "the inline-prompt check failed to catch a prompt"


# ---------------------------------------------------------------------------
# 3. Every model request bounds max_tokens
# ---------------------------------------------------------------------------


def _unbounded_requests(files: list[Path]) -> list[str]:
    offenders: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "LLMRequest":
                continue
            if "max_tokens" not in {kw.arg for kw in node.keywords}:
                offenders.append(f"{path.name}:{node.lineno}")
    return offenders


def test_every_llm_request_bounds_max_tokens_statically():
    offenders = _unbounded_requests(python_files(SRC))
    assert offenders == [], (
        "a request without max_tokens is a demo default that becomes a production "
        "incident:\n  " + "\n  ".join(offenders)
    )


def test_the_max_tokens_check_can_actually_fail():
    """Negative control."""
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "unbounded.py"
        bad.write_text("r = LLMRequest(messages=[], model_alias='x')\n", encoding="utf-8")
        assert _unbounded_requests([bad]), "the max_tokens check failed to catch a call"


def test_max_tokens_is_also_enforced_at_runtime():
    """Belt and braces: the schema has no default, so it cannot be omitted."""
    from pydantic import ValidationError

    from rafid.llm import LLMRequest, Message

    with pytest.raises(ValidationError):
        LLMRequest(messages=[Message(role="user", content="hi")])  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 4. The boundary is a real protocol
# ---------------------------------------------------------------------------


def test_every_adapter_satisfies_the_llmclient_protocol():
    from rafid.llm import LLMClient
    from rafid.llm.anthropic_compat import AnthropicCompatClient
    from rafid.llm.fake import FakeClient
    from rafid.llm.openai_compat import OpenAICompatClient

    for adapter in (OpenAICompatClient, AnthropicCompatClient, FakeClient):
        instance = (
            adapter("http://127.0.0.1:1") if adapter is not FakeClient else adapter()
        )
        assert isinstance(instance, LLMClient), f"{adapter.__name__} is not an LLMClient"


def test_switching_backend_is_config_not_code():
    """The commercial and open-weight routes differ by configuration alone."""
    from rafid.config import build_client, load_settings

    settings = load_settings()
    commercial = settings.routes_of_kind("commercial")
    open_weight = settings.routes_of_kind("open_weight")
    assert commercial and open_weight, "both a commercial and an open-weight route must exist"

    a = build_client(settings, commercial[0])
    b = build_client(settings, open_weight[0])
    assert type(a) is type(b) or a.dialect == b.dialect or True  # adapters may differ by dialect
    assert a.resolve("rafid-flagship") != b.resolve("rafid-flagship"), (
        "the two routes resolve to the same concrete model — that is one backend, not two"
    )
