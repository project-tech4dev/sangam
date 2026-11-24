"""Provider-agnostic model resolution."""

from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.core.config import get_settings

SUPPORTED_PROVIDERS = {"anthropic", "openai", "google_genai", "compat"}
# An OpenAI-compatible endpoint (a hosted open model) on its own URL and key, so OPENAI_API_KEY stays the graph's.
COMPAT = "compat"
# Haiku 5.5 thinks at medium effort by default; the utility tier's short, fixed-shape jobs need little or none.
# Matched by prefix, so a dated snapshot of the same model gets it too.
EFFORT = {"claude-haiku-5-5": "low"}


def resolve_model(spec: str) -> BaseChatModel:
    """Resolve a "provider:model_name" spec into a chat model instance."""
    if ":" not in spec:
        raise ValueError(
            f"Invalid model spec {spec!r}: expected 'provider:model_name', "
            f"e.g. 'anthropic:claude-opus-5-5'"
        )
    provider, name = spec.split(":", 1)
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported provider {provider!r}: expected one of {sorted(SUPPORTED_PROVIDERS)}"
        )
    if provider == COMPAT:
        settings = get_settings()
        if not settings.compat_base_url:
            raise ValueError(f"{spec!r} needs COMPAT_BASE_URL (and COMPAT_API_KEY) set")
        return init_chat_model(name, model_provider="openai", base_url=settings.compat_base_url,
                               api_key=settings.compat_api_key, stream_usage=True)
    effort = next((level for prefix, level in EFFORT.items() if name.startswith(prefix)), None)
    kwargs = {"output_config": {"effort": effort}} if effort else {}
    return init_chat_model(name, model_provider=provider, **kwargs)
