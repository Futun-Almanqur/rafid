"""Configuration: routes, aliases, prices, switches — and the client factory.

The load-bearing property: `build_client(settings, "onprem")` and
`build_client(settings, "primary")` differ by nothing but a name. No branch in
this file asks which provider it is; it asks which *dialect* the route declares
and hands the adapter a base_url. That is what makes "switchable by config
rather than by code" a fact rather than an aspiration.

Environment overrides, per route, no code change:

    RAFID_PRIMARY_BASE_URL=https://api.openai.com/v1
    RAFID_PRIMARY_API_KEY=sk-...
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from rafid.llm.anthropic_compat import AnthropicCompatClient
from rafid.llm.interfaces import LLMClient
from rafid.llm.openai_compat import OpenAICompatClient
from rafid.llm.resilient import ResilientClient

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs" / "rafid.yaml"


class Price(BaseModel):
    input_per_mtok: float
    cached_input_per_mtok: float
    output_per_mtok: float


class PriceSheet(BaseModel):
    sheets: dict[str, Price]

    def for_model(self, model_id: str) -> Price:
        return self.sheets.get(model_id, self.sheets["default"])


class Route(BaseModel):
    name: str
    dialect: str
    base_url: str
    api_key: str = "local-gateway-no-key"
    residency: str = "cloud"
    kind: str = "commercial"  # commercial | open_weight
    aliases: dict[str, str] = Field(default_factory=dict)

    def resolve(self, alias: str) -> str:
        return self.aliases.get(alias, self.aliases.get("rafid-default", alias))


class Settings(BaseModel):
    routes: dict[str, Route]
    primary_route: str
    fallback_route: str
    cheap_route: str
    prices: PriceSheet
    self_host: dict = Field(default_factory=dict)
    cache_enabled: bool = False
    semantic_cache_enabled: bool = False
    routing_enabled: bool = False

    def route(self, name: str) -> Route:
        if name not in self.routes:
            raise KeyError(f"no route {name!r}; configured: {sorted(self.routes)}")
        return self.routes[name]

    def routes_of_kind(self, kind: str) -> list[str]:
        return [n for n, r in self.routes.items() if r.kind == kind]


def load_settings(path: str | Path = DEFAULT_CONFIG, *, gateway_base: str | None = None) -> Settings:
    """Load YAML, then let the environment override any route's URL or key.

    ``gateway_base`` (e.g. ``http://127.0.0.1:53211``) repoints every route whose
    configured base_url is the local gateway — which is what the notebook needs
    when it picks a free port.
    """
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    routes: dict[str, Route] = {}
    for name, body in spec["routes"].items():
        base_url = body["base_url"]
        if gateway_base and "127.0.0.1:8080" in base_url:
            base_url = base_url.replace("http://127.0.0.1:8080", gateway_base.rstrip("/"))
        env = name.upper()
        routes[name] = Route(
            name=name,
            dialect=body["dialect"],
            base_url=os.environ.get(f"RAFID_{env}_BASE_URL", base_url),
            api_key=os.environ.get(f"RAFID_{env}_API_KEY", body.get("api_key", "local-gateway-no-key")),
            residency=body.get("residency", "cloud"),
            kind=body.get("kind", "commercial"),
            aliases=body.get("aliases", {}),
        )

    return Settings(
        routes=routes,
        primary_route=spec["primary_route"],
        fallback_route=spec["fallback_route"],
        cheap_route=spec["cheap_route"],
        prices=PriceSheet(sheets={k: Price(**v) for k, v in spec["prices"].items()}),
        self_host=spec.get("self_host", {}),
        cache_enabled=_flag("RAFID_CACHE_ENABLED", spec.get("cache_enabled", False)),
        semantic_cache_enabled=_flag(
            "RAFID_SEMANTIC_CACHE_ENABLED", spec.get("semantic_cache_enabled", False)
        ),
        routing_enabled=_flag("RAFID_ROUTING_ENABLED", spec.get("routing_enabled", False)),
    )


def _flag(var: str, default: bool) -> bool:
    raw = os.environ.get(var)
    return default if raw is None else raw not in ("0", "", "false", "False")


#: The one place a dialect name becomes a class. Adding a third dialect is a row
#: here and a new file in llm/ — never an `if` in application code.
ADAPTERS = {"openai": OpenAICompatClient, "anthropic": AnthropicCompatClient}


def build_client(settings: Settings, route_name: str, **kwargs) -> LLMClient:
    route = settings.route(route_name)
    adapter = ADAPTERS[route.dialect]
    return adapter(
        route.base_url,
        api_key=route.api_key,
        route=route.name,
        aliases=route.aliases,
        **kwargs,
    )


def build_resilient_client(
    settings: Settings, *, primary: str | None = None, fallback: str | None = None, **kwargs
) -> ResilientClient:
    """Primary route, then the fallback hop. Reliability policy in one place."""
    primary = primary or settings.primary_route
    fallback = fallback or settings.fallback_route
    chain = [(primary, build_client(settings, primary))]
    if fallback and fallback != primary:
        chain.append((fallback, build_client(settings, fallback)))
    return ResilientClient(chain, **kwargs)
