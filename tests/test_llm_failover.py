"""
Regression suite: sticky primary -> fallback failover.

Gemini's free tier returns 429 persistently once the quota is spent. The client did
fall back to Groq correctly, but it re-probed Gemini on EVERY call, so each request
paid a doomed round trip and latency roughly doubled. Failover is now sticky, with a
periodic probe so a recovered primary is picked back up.
"""
from __future__ import annotations

from src.config import Settings
from src.core.llm import LLMClient, LLMMessage, LLMRequest
from src.core.llm.errors import LLMRateLimitError
from src.core.llm.types import LLMResponse, TokenUsage


def _client(primary="gemini", fallback="groq") -> LLMClient:
    s = Settings(_env_file=None, llm_provider=primary, llm_fallback_provider=fallback,
                 gemini_api_key="k", groq_api_key="k")
    return LLMClient(s)


def _req(n: int) -> LLMRequest:
    # distinct content per call so the response cache never masks dispatch behaviour
    return LLMRequest(system_prompt="s", messages=[LLMMessage.user(f"m{n}")],
                      agent_name="t", sandbox_response=None)


def _patch(client: LLMClient, primary_fails: bool):
    """Record dispatches; primary optionally always rate-limits."""
    seen: list[str] = []

    async def fake_dispatch(provider, request):
        seen.append(provider)
        if provider == client.provider and primary_fails:
            raise LLMRateLimitError("Rate limited (429)")
        return LLMResponse(content="ok", provider=provider, model="m", usage=TokenUsage())

    client._dispatch = fake_dispatch
    return seen


async def test_primary_is_skipped_after_repeated_failures():
    c = _client()
    seen = _patch(c, primary_fails=True)

    for i in range(12):
        resp = await c.complete(_req(i))
        assert resp.provider == "groq"

    primary_attempts = seen.count("gemini")
    assert primary_attempts <= c._FAILOVER_AFTER, (
        f"primary was retried {primary_attempts}x across 12 calls; expected it to be "
        f"skipped after {c._FAILOVER_AFTER} failures")
    assert seen.count("groq") == 12
    assert c._failed_over is True
    assert c.active_provider == "groq"


async def test_healthy_primary_is_never_bypassed():
    c = _client()
    seen = _patch(c, primary_fails=False)

    for i in range(6):
        resp = await c.complete(_req(i))
        assert resp.provider == "gemini"

    assert "groq" not in seen
    assert c._failed_over is False


async def test_primary_is_probed_again_and_recovers():
    c = _client()
    c._PROBE_PRIMARY_EVERY = 3          # shorten for the test
    state = {"fails": True}
    seen: list[str] = []

    async def fake_dispatch(provider, request):
        seen.append(provider)
        if provider == "gemini" and state["fails"]:
            raise LLMRateLimitError("Rate limited (429)")
        return LLMResponse(content="ok", provider=provider, model="m", usage=TokenUsage())

    c._dispatch = fake_dispatch

    for i in range(4):                  # trip the breaker
        await c.complete(_req(i))
    assert c._failed_over is True

    state["fails"] = False              # quota window resets
    got = [await c.complete(_req(100 + i)) for i in range(6)]

    assert any(r.provider == "gemini" for r in got), "primary was never re-probed"
    assert c._failed_over is False
    assert c.active_provider == "gemini"


async def test_blank_fallback_env_value_disables_failover_without_crashing():
    """.env documents `LLM_FALLBACK_PROVIDER=` to disable failover."""
    s = Settings(_env_file=None, llm_provider="gemini", llm_fallback_provider="",
                 gemini_api_key="k")
    assert s.llm_fallback_provider is None


async def test_no_fallback_configured_degrades_to_sandbox():
    c = _client(fallback=None)
    _patch(c, primary_fails=True)
    resp = await c.complete(_req(0))
    assert resp.provider == "sandbox"
    assert c.degraded is True


# ------------------------------------------------- last resort: offline sandbox
def _patch_all_fail(client: LLMClient):
    """Both live providers fail; the sandbox tier must still answer."""
    seen: list[str] = []

    async def fake_dispatch(provider, request):
        seen.append(provider)
        if provider == "sandbox":
            return client._sandbox(request)
        raise LLMRateLimitError("Rate limited (429)")

    client._dispatch = fake_dispatch
    return seen


async def test_both_providers_down_degrades_to_sandbox_instead_of_raising():
    """Two exhausted free tiers used to surface as an unhandled 500."""
    c = _client()
    _patch_all_fail(c)

    resp = await c.complete(_req(0))

    assert resp.provider == "sandbox", "expected the offline model to answer"
    assert c.degraded is True
    assert c.active_provider == "sandbox"


async def test_degraded_mode_stops_hammering_dead_providers():
    c = _client()
    seen = _patch_all_fail(c)

    for i in range(15):
        resp = await c.complete(_req(i))
        assert resp.provider == "sandbox"

    live_attempts = seen.count("gemini") + seen.count("groq")
    assert live_attempts < 15, (
        f"made {live_attempts} live attempts across 15 calls; degraded mode should "
        f"stop retrying dead providers on every call")


async def test_degraded_response_uses_the_agents_own_heuristic():
    """The offline model returns the agent's sandbox_response, not a generic stub."""
    c = _client()
    _patch_all_fail(c)

    req = LLMRequest(system_prompt="s", messages=[LLMMessage.user("m")],
                     agent_name="request_parser",
                     sandbox_response='{"specialty": "Orthodontics"}')
    resp = await c.complete(req)
    assert resp.content == '{"specialty": "Orthodontics"}'


async def test_degraded_mode_recovers_when_a_provider_comes_back():
    c = _client()
    c._PROBE_PRIMARY_EVERY = 3
    state = {"down": True}

    async def fake_dispatch(provider, request):
        if provider == "sandbox":
            return c._sandbox(request)
        if state["down"]:
            raise LLMRateLimitError("Rate limited (429)")
        return LLMResponse(content="live", provider=provider, model="m", usage=TokenUsage())

    c._dispatch = fake_dispatch

    for i in range(3):
        await c.complete(_req(i))
    assert c.degraded is True

    state["down"] = False
    got = [await c.complete(_req(100 + i)) for i in range(6)]

    assert any(r.provider == "gemini" for r in got), "never recovered off the sandbox"
    assert c.degraded is False


async def test_degradation_is_visible_in_the_call_log():
    """The API surfaces call_log, so a degraded encounter must be auditable."""
    c = _client()
    _patch_all_fail(c)
    await c.complete(_req(0))
    assert c.call_log[-1]["provider"] == "sandbox"


async def test_response_cache_still_prevents_duplicate_calls():
    c = _client()
    seen = _patch(c, primary_fails=False)
    same = _req(0)
    await c.complete(same)
    await c.complete(same)
    assert len(seen) == 1, "deterministic request should be served from cache"
