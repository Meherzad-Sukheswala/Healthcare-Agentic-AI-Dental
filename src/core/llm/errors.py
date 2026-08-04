"""LLM error hierarchy with retry classification."""
from __future__ import annotations


class LLMError(Exception):
    """Base class for all LLM-layer errors."""

    retryable: bool = False


class LLMConfigError(LLMError):
    """Missing/invalid provider configuration (e.g. no API key)."""

    retryable = False


class LLMAuthError(LLMError):
    """Provider rejected the credentials (401/403)."""

    retryable = False


class LLMRateLimitError(LLMError):
    """Provider rate-limited or overloaded (429/503)."""

    retryable = True


class LLMTransportError(LLMError):
    """Network/transport failure talking to the provider."""

    retryable = True


class LLMResponseError(LLMError):
    """Provider returned an unusable / unparseable response."""

    retryable = False
