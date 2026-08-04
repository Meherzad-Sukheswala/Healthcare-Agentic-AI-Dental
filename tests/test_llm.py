"""The sandbox LLM provider is deterministic and offline."""
from src.config import Settings
from src.core.llm import LLMClient, LLMMessage, LLMRequest


async def test_sandbox_echo_deterministic():
    client = LLMClient(Settings(_env_file=None, llm_provider="sandbox"))
    req = LLMRequest(system_prompt="sys", messages=[LLMMessage.user("hello")], agent_name="t")
    r1 = await client.complete(req)
    r2 = await client.complete(req)
    assert r1.provider == "sandbox"
    assert r1.content == r2.content        # deterministic


async def test_sandbox_scripted_response():
    client = LLMClient(Settings(_env_file=None, llm_provider="sandbox"))
    req = LLMRequest(
        system_prompt="sys",
        messages=[LLMMessage.user("x")],
        sandbox_response='{"triage": "urgent"}',
    )
    r = await client.complete(req)
    assert r.content == '{"triage": "urgent"}'


async def test_call_alias():
    client = LLMClient(Settings(_env_file=None, llm_provider="sandbox"))
    r = await client.call(LLMRequest(system_prompt="s", messages=[LLMMessage.user("y")]))
    assert r.usage.total_tokens >= 0
