"""Interchangeable model providers. The agent loop only sees `ModelProvider`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import ModelProvider, ServerToolEvent, ToolCall, ToolResult, ToolSpec, Turn

if TYPE_CHECKING:
    from ..config import Settings

__all__ = [
    "ModelProvider",
    "ServerToolEvent",
    "ToolCall",
    "ToolResult",
    "ToolSpec",
    "Turn",
    "make_provider",
]


def make_provider(settings: Settings) -> ModelProvider:
    if settings.provider == "anthropic":
        from .anthropic_ import AnthropicProvider

        return AnthropicProvider(api_key=settings.anthropic_api_key, effort=settings.effort)
    if settings.provider == "openai":
        from .openai_ import OpenAIProvider

        return OpenAIProvider(api_key=settings.openai_api_key)
    raise ValueError(f"unknown provider {settings.provider!r} (anthropic or openai)")
