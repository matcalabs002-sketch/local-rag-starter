"""Small, side-effect-free helpers used by the Streamlit interface."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any
import re


def visible_settings(settings: Any) -> dict[str, Any]:
    """Return public configuration values without credentials or connection URLs."""
    raw = asdict(settings) if is_dataclass(settings) else vars(settings)
    hidden = {
        "database_url",
        "ca_file",
        "openai_api_key",
        "anthropic_api_key",
        "api_key",
        "password",
        "token",
        "secret",
    }
    return {key: val for key, val in raw.items() if key.lower() not in hidden}


def preview_chunks(text: str, chunk_size: int, overlap: int, separators: list[str] | None = None) -> list[str]:
    """Preview the same recursive splitting approach used by document indexing."""
    from .loaders import preview_chunks as split_preview

    return split_preview(text, chunk_size, overlap, separators)


def provider_catalog() -> dict[str, list[str]]:
    """Discover supported providers from the single adapter capability catalog."""
    from .models import Models

    capabilities = Models.capabilities()
    return {
        task: list(dict.fromkeys(item.provider for item in capabilities if item.task == task))
        for task in ("chat", "embedding")
    }


def provider_models(task: str, provider: str) -> list[str]:
    from .models import Models

    for capability in Models.capabilities():
        if capability.task == task and capability.provider == provider:
            return list(capability.models)
    return []


def literal_label(value: str) -> str:
    """Escape untrusted filenames/titles in Streamlit's Markdown-enabled labels."""
    return re.sub(r"([\\`*_{}\[\]()<>#!|])", r"\\\1", value)
