"""Config loads and selects the active model per provider."""
from src.config import Settings


def test_defaults_sandbox():
    s = Settings(_env_file=None)
    assert s.llm_provider == "sandbox"
    assert s.active_model() == "sandbox-echo-1"


def test_active_model_switch():
    s = Settings(_env_file=None, llm_provider="groq", groq_model="llama-3.3-70b-versatile")
    assert s.active_model() == "llama-3.3-70b-versatile"
