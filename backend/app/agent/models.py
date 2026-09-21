"""Provider-agnostic model resolution."""

from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

SUPPORTED_PROVIDERS = {"anthropic", "openai", "google_genai"}


def resolve_model(spec: str) -> BaseChatModel:
    """Resolve a "provider:model_name" spec into a chat model instance."""
    if ":" not in spec:
        raise ValueError(
            f"Invalid model spec {spec!r}: expected 'provider:model_name', "
            f"e.g. 'anthropic:claude-sonnet-5'"
        )
    provider, name = spec.split(":", 1)
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported provider {provider!r}: expected one of {sorted(SUPPORTED_PROVIDERS)}"
        )
    return init_chat_model(name, model_provider=provider)
