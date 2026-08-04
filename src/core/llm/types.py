"""
src/core/llm/types.py

Provider-neutral request/response types for the LLM abstraction layer.
Agents build an LLMRequest; the client returns an LLMResponse regardless of
which provider (Groq / Gemini / Anthropic / sandbox) actually served it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Role = Literal["user", "assistant"]


@dataclass
class LLMMessage:
    role: Role
    content: str

    @staticmethod
    def user(content: str) -> "LLMMessage":
        return LLMMessage("user", content)

    @staticmethod
    def assistant(content: str) -> "LLMMessage":
        return LLMMessage("assistant", content)


@dataclass
class LLMRequest:
    system_prompt: str
    messages: list[LLMMessage]
    max_tokens: int = 512
    temperature: float = 0.0
    agent_name: str = "unknown"
    # Optional deterministic answer the sandbox provider should echo back.
    # Lets tests/demos get predictable structured output with zero network.
    sandbox_response: str | None = None


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)
