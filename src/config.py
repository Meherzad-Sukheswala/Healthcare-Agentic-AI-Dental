"""
src/config.py

Central, provider-agnostic application settings loaded from environment / .env.
Nothing secret is hardcoded; every credential comes from the environment.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["sandbox", "groq", "gemini", "anthropic"]
EHRMode = Literal["sandbox", "fhir_public"]


class Settings(BaseSettings):
    """Runtime configuration. Values come from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # --- LLM ---
    llm_provider: LLMProvider = "gemini"
    # Provider used automatically if the primary provider call fails.
    # Set to None (LLM_FALLBACK_PROVIDER=) to disable fallback.
    llm_fallback_provider: LLMProvider | None = "groq"
    llm_max_tokens: int = 512
    llm_temperature: float = 0.0

    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # --- Integrations ---
    ehr_mode: EHRMode = "sandbox"
    fhir_public_base_url: str = "https://hapi.fhir.org/baseR4"

    # --- Application ---
    environment: str = "development"
    log_level: str = "INFO"
    log_json: bool = False

    # --- Billing policy (provider-configurable) ---
    # Default self-pay / prompt-pay discount applied to uninsured patients.
    # 0.0 = no discount. A per-encounter value overrides this. e.g. 0.20 = 20%.
    self_pay_discount_pct: float = 0.0

    # Sales tax applied ONLY to line items explicitly flagged taxable (non-exempt
    # retail/ancillary items). Professional services and exempt items (e.g.
    # prescriptions) are never taxed. e.g. 0.08 = 8%.
    sales_tax_pct: float = 0.08

    @field_validator("llm_fallback_provider", mode="before")
    @classmethod
    def _blank_fallback_is_none(cls, v):
        """`LLM_FALLBACK_PROVIDER=` (blank) means "no fallback".

        .env documents blanking this to disable failover, but an empty string is not
        a member of the LLMProvider literal, so following that instruction used to
        crash the app at startup with a validation error. Treat blank as None.
        """
        if isinstance(v, str) and not v.strip():
            return None
        return v

    def model_for(self, provider: LLMProvider) -> str:
        return {
            "sandbox": "sandbox-echo-1",
            "groq": self.groq_model,
            "gemini": self.gemini_model,
            "anthropic": self.anthropic_model,
        }[provider]

    def active_model(self) -> str:
        return self.model_for(self.llm_provider)


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
