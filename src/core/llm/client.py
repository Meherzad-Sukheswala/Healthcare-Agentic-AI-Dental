"""
src/core/llm/client.py

The single async LLM entry point used by every AI agent. It hides the provider
behind one interface, so switching Groq -> Gemini -> Anthropic is a config change
with zero agent-code changes.

Providers:
  - sandbox   : deterministic, offline. Returns request.sandbox_response if given,
                otherwise a stable echo. Used for tests, CI, and reliable demos.
  - groq      : OpenAI-compatible chat completions endpoint.
  - gemini    : Google Generative Language API.
  - anthropic : Anthropic Messages API.

Real providers are called over HTTP via httpx (no vendor SDKs). Keys come from
Settings (environment / .env).
"""
from __future__ import annotations

import hashlib
import json

import httpx

from src.config import Settings, get_settings
from src.logging_setup import get_logger

from .errors import LLMAuthError, LLMConfigError, LLMError, LLMRateLimitError, LLMResponseError, LLMTransportError
from .types import LLMRequest, LLMResponse, TokenUsage

log = get_logger(__name__)

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class LLMClient:
    """Async, provider-agnostic LLM client."""

    # Cap on cached entries; cleared wholesale when exceeded (demo-simple).
    _CACHE_MAX = 1024

    # Consecutive primary failures before we stop trying the primary on every call
    # and go straight to the fallback. Gemini's free tier 429s persistently once the
    # quota is hit; re-probing it every call cost a wasted round trip and roughly
    # doubled latency, since the fallback answered anyway.
    _FAILOVER_AFTER = 2
    # After this many calls served by the fallback, probe the primary once more, so a
    # recovered primary (quota window reset) is picked back up automatically.
    _PROBE_PRIMARY_EVERY = 25
    # Last resort when BOTH configured providers are down. The sandbox provider is the
    # offline deterministic model: it returns each agent's own `sandbox_response`
    # heuristic. Without this, two rate-limited providers surfaced as an unhandled 500
    # and killed the encounter. Responses carry provider="sandbox", so the API's
    # `llm_calls` field shows plainly that no live model produced them.
    _LAST_RESORT = "sandbox"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.provider = self.settings.llm_provider
        self.fallback_provider = self.settings.llm_fallback_provider
        self.model = self.settings.active_model()
        # Content-addressed response cache. The encounter pipeline replays from
        # the start on every resume, so without this each replay would re-call
        # the LLM for agents that already ran. With temperature=0 the mapping
        # request -> response is deterministic, so reusing it is exact.
        self._cache: dict[str, LLMResponse] = {}
        # Rolling record of LLM activity (live calls + cache reuse) so the API
        # can report exactly where the model was invoked. Cleared per encounter
        # pass by the orchestrator/API layer.
        self.call_log: list[dict] = []
        # Failover state: once the primary has failed repeatedly we route straight
        # to the fallback instead of paying a failed request on every single call.
        self._primary_failures = 0
        self._failed_over = False
        self._calls_since_failover = 0
        # Set once both live providers have failed and we dropped to the offline model.
        self._degraded_to_sandbox = False

    @property
    def active_provider(self) -> str:
        """The provider calls are currently routed to (may be a fallback tier)."""
        if self._degraded_to_sandbox:
            return self._LAST_RESORT
        return self.fallback_provider if self._failed_over else self.provider

    @property
    def degraded(self) -> bool:
        """True when no live provider is reachable and the offline model is serving."""
        return self._degraded_to_sandbox

    @staticmethod
    def _cache_key(request: LLMRequest) -> str:
        h = hashlib.sha256()
        h.update(request.agent_name.encode())
        h.update(b"\x00"); h.update(request.system_prompt.encode())
        h.update(b"\x00"); h.update(str(request.max_tokens).encode())
        h.update(b"\x00"); h.update(str(request.temperature).encode())
        for m in request.messages:
            h.update(b"\x00"); h.update(m.role.encode())
            h.update(b"\x00"); h.update(m.content.encode())
        return h.hexdigest()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Primary API. `.call()` is a backward-compatible alias.

        Deterministic requests (temperature == 0) are cached so pipeline
        replays reuse the prior answer instead of re-calling the provider —
        the LLM is only hit the first time a given request is seen.
        """
        cacheable = request.temperature == 0
        key = self._cache_key(request) if cacheable else None
        if key is not None and key in self._cache:
            cached = self._cache[key]
            log.debug("llm_cache_hit", agent=request.agent_name, provider=self.provider)
            self.call_log.append({"agent": request.agent_name, "provider": cached.provider,
                                  "model": cached.model, "cached": True})
            return cached
        resp = await self._complete_uncached(request)
        if key is not None:
            if len(self._cache) >= self._CACHE_MAX:
                self._cache.clear()
            self._cache[key] = resp
        self.call_log.append({"agent": request.agent_name, "provider": resp.provider,
                              "model": resp.model, "cached": False})
        return resp

    async def _complete_uncached(self, request: LLMRequest) -> LLMResponse:
        """Three-tier routing: primary -> fallback -> offline sandbox model.

        * A single primary failure transparently retries the configured fallback.
        * After `_FAILOVER_AFTER` consecutive primary failures the primary is skipped
          entirely, so a persistently rate-limited provider costs one wasted request
          rather than one per call. The primary is re-probed every
          `_PROBE_PRIMARY_EVERY` calls, so recovery is picked up automatically.
        * If BOTH live providers fail, the offline sandbox model answers instead of
          the request raising. Two exhausted free tiers previously surfaced as an
          unhandled 500 and aborted the encounter. Degraded responses are tagged
          provider="sandbox" in `call_log`, so the API reports them honestly.
        """
        fb = self.fallback_provider
        has_fallback = bool(fb) and fb != self.provider

        # Fully degraded: serve offline, re-probing the primary periodically.
        if self._degraded_to_sandbox:
            self._calls_since_failover += 1
            if self._calls_since_failover % self._PROBE_PRIMARY_EVERY == 0:
                probed = await self._probe_primary(request)
                if probed is not None:
                    return probed
            return self._sandbox(request)

        # Failed over to the fallback: skip the known-bad primary, probe occasionally.
        if has_fallback and self._failed_over:
            self._calls_since_failover += 1
            if self._calls_since_failover % self._PROBE_PRIMARY_EVERY == 0:
                probed = await self._probe_primary(request)
                if probed is not None:
                    return probed
            try:
                return await self._dispatch(fb, request)
            except LLMError as fb_exc:
                return self._degrade(request, reason=f"fallback={fb}: {fb_exc}")

        try:
            resp = await self._dispatch(self.provider, request)
            self._primary_failures = 0
            return resp
        except LLMError as primary_exc:
            if not has_fallback:
                return self._degrade(request, reason=f"primary={self.provider}: {primary_exc}")
            self._primary_failures += 1
            if self._primary_failures >= self._FAILOVER_AFTER and not self._failed_over:
                self._failed_over = True
                self._calls_since_failover = 0
                log.warning("llm_failed_over", primary=self.provider, fallback=fb,
                            consecutive_failures=self._primary_failures,
                            detail="routing directly to fallback until the primary recovers")
            log.warning(
                "llm_fallback",
                primary=self.provider,
                fallback=fb,
                agent=request.agent_name,
                error=str(primary_exc),
            )
            try:
                return await self._dispatch(fb, request)
            except LLMError as fb_exc:
                return self._degrade(
                    request,
                    reason=(f"primary={self.provider}: {primary_exc}; "
                            f"fallback={fb}: {fb_exc}"))

    async def _probe_primary(self, request: LLMRequest) -> LLMResponse | None:
        """Try the primary once; on success clear all degraded state."""
        try:
            resp = await self._dispatch(self.provider, request)
        except LLMError as exc:
            log.debug("llm_primary_still_down", primary=self.provider, error=str(exc))
            return None
        log.info("llm_primary_recovered", primary=self.provider, agent=request.agent_name)
        self._failed_over = False
        self._degraded_to_sandbox = False
        self._primary_failures = 0
        self._calls_since_failover = 0
        return resp

    def _degrade(self, request: LLMRequest, reason: str) -> LLMResponse:
        """Serve the offline model because no live provider is reachable."""
        if not self._degraded_to_sandbox:
            self._degraded_to_sandbox = True
            self._calls_since_failover = 0
            log.error("llm_degraded_to_sandbox", agent=request.agent_name, reason=reason,
                      detail="no live LLM provider reachable; serving the offline "
                             "deterministic model so the encounter can continue")
        return self._sandbox(request)

    async def _dispatch(self, provider: str, request: LLMRequest) -> LLMResponse:
        model = self.settings.model_for(provider)
        log.debug("llm_call", provider=provider, model=model, agent=request.agent_name)
        if provider == "sandbox":
            return self._sandbox(request)
        if provider == "groq":
            return await self._groq(request, model)
        if provider == "gemini":
            return await self._gemini(request, model)
        if provider == "anthropic":
            return await self._anthropic(request, model)
        raise LLMConfigError(f"Unknown LLM provider: {provider}")

    # backward-compatible alias used by some agents
    async def call(self, request: LLMRequest) -> LLMResponse:
        return await self.complete(request)

    # ---------------- sandbox (offline, deterministic) ----------------
    def _sandbox(self, request: LLMRequest) -> LLMResponse:
        if request.sandbox_response is not None:
            content = request.sandbox_response
        else:
            user = " ".join(m.content for m in request.messages if m.role == "user")
            digest = hashlib.sha256((request.system_prompt + user).encode()).hexdigest()[:8]
            content = json.dumps({"echo": user[:200], "agent": request.agent_name, "trace": digest})
        return LLMResponse(
            content=content,
            provider="sandbox",
            model="sandbox-echo-1",
            usage=TokenUsage(prompt_tokens=len(request.system_prompt) // 4, completion_tokens=len(content) // 4),
        )

    # ---------------- Groq (OpenAI-compatible) ----------------
    async def _groq(self, request: LLMRequest, model: str) -> LLMResponse:
        if not self.settings.groq_api_key:
            raise LLMConfigError("GROQ_API_KEY is not set")
        payload = {
            "model": model,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "messages": [{"role": "system", "content": request.system_prompt}]
            + [{"role": m.role, "content": m.content} for m in request.messages],
        }
        data = await self._post_json(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.groq_api_key}"},
            payload=payload,
        )
        try:
            content = data["choices"][0]["message"]["content"]
            u = data.get("usage", {})
            usage = TokenUsage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError(f"Malformed Groq response: {exc}") from exc
        return LLMResponse(content=content, provider="groq", model=model, usage=usage)

    # ---------------- Gemini ----------------
    async def _gemini(self, request: LLMRequest, model: str) -> LLMResponse:
        if not self.settings.gemini_api_key:
            raise LLMConfigError("GEMINI_API_KEY is not set")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={self.settings.gemini_api_key}"
        )
        payload = {
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": m.content}]} for m in request.messages],
            "generationConfig": {"temperature": request.temperature, "maxOutputTokens": request.max_tokens},
        }
        data = await self._post_json(url, headers={}, payload=payload)
        try:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError(f"Malformed Gemini response: {exc}") from exc
        return LLMResponse(content=content, provider="gemini", model=model, usage=TokenUsage())

    # ---------------- Anthropic ----------------
    async def _anthropic(self, request: LLMRequest, model: str) -> LLMResponse:
        if not self.settings.anthropic_api_key:
            raise LLMConfigError("ANTHROPIC_API_KEY is not set")
        payload = {
            "model": model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": request.system_prompt,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }
        data = await self._post_json(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.settings.anthropic_api_key, "anthropic-version": "2023-06-01"},
            payload=payload,
        )
        try:
            content = "".join(block.get("text", "") for block in data["content"])
            u = data.get("usage", {})
            usage = TokenUsage(u.get("input_tokens", 0), u.get("output_tokens", 0))
        except (KeyError, TypeError) as exc:
            raise LLMResponseError(f"Malformed Anthropic response: {exc}") from exc
        return LLMResponse(content=content, provider="anthropic", model=model, usage=usage)

    # ---------------- shared HTTP helper ----------------
    async def _post_json(self, url: str, headers: dict, payload: dict) -> dict:
        headers = {"Content-Type": "application/json", **headers}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise LLMTransportError(f"Transport error: {exc}") from exc
        if resp.status_code in (401, 403):
            raise LLMAuthError(f"Auth failed ({resp.status_code})")
        if resp.status_code in (429, 503):
            raise LLMRateLimitError(f"Rate limited ({resp.status_code})")
        if resp.status_code >= 400:
            raise LLMResponseError(f"Provider error {resp.status_code}: {resp.text[:200]}")
        return resp.json()
