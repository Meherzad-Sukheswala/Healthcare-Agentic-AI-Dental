"""
Request Parser (single task: turn a free-text request into structured intake).

LLM-backed (PARTIAL). In sandbox/offline mode it returns a deterministic heuristic
parse via LLMRequest.sandbox_response, so tests and demos are reproducible; with a
real provider the model does the parsing. Either way the output shape is identical.

The specialty is CONSTRAINED to the specialties the provider directory can actually
staff. An unconstrained model happily answers "Orthopedics" or "Pulmonology", which
no seeded provider matches — that used to abort the whole encounter downstream. The
allowed list is injected into the prompt, and whatever comes back is snapped onto
that list, so the value handed to ProviderMatcher is always satisfiable.
"""
from __future__ import annotations

import json

from src.core.llm import LLMMessage, LLMRequest
from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

_SYSTEM_TMPL = (
    "You are a dental scheduling intake parser. Given a patient's free-text request, "
    'return STRICT JSON: {{"specialty": str, "reason": str, "preferred_provider_name": str}}. '
    "The specialty MUST be chosen verbatim from this list of specialties our clinic "
    "staffs: {allowed}. Pick the closest fit; if nothing fits well, use "
    "'{default}'. Do not invent a specialty outside the list."
)

# Used only if the directory cannot be reached at all.
_FALLBACK_SPECIALTIES = ["General Dentistry", "Orthodontics", "Oral & Maxillofacial Surgery"]
DEFAULT_SPECIALTY = "General Dentistry"

# Symptom -> specialty hints for the offline heuristic. Values are snapped against
# the live directory afterwards, so a hint the directory cannot staff degrades
# gracefully instead of failing the encounter.
_SPECIALTY_HINTS = {
    "brace": "Orthodontics", "crooked": "Orthodontics", "bite": "Orthodontics",
    "align": "Orthodontics", "invisalign": "Orthodontics",
    "wisdom": "Oral & Maxillofacial Surgery", "impacted": "Oral & Maxillofacial Surgery",
    "extraction": "Oral & Maxillofacial Surgery", "jaw surgery": "Oral & Maxillofacial Surgery",
}


class RequestParser(Agent):
    name = "request_parser"
    automation = Automation.PARTIAL

    def __init__(self, llm, registry=None):
        self.llm = llm
        self.reg = registry

    async def _allowed_specialties(self) -> list[str]:
        directory = getattr(self.reg, "directory", None)
        getter = getattr(directory, "specialties", None)
        if getter is None:
            return list(_FALLBACK_SPECIALTIES)
        try:
            allowed = [s for s in await getter() if s]
        except Exception:  # directory unavailable — never block intake on this
            return list(_FALLBACK_SPECIALTIES)
        return allowed or list(_FALLBACK_SPECIALTIES)

    @staticmethod
    def _default_for(allowed: list[str]) -> str:
        for s in allowed:
            if s.lower() == DEFAULT_SPECIALTY.lower():
                return s
        return allowed[0]

    @staticmethod
    def _snap(value: str, allowed: list[str], default: str) -> str:
        """Map any model output onto a specialty the directory can staff."""
        v = (value or "").strip().lower()
        if not v:
            return default
        for s in allowed:                       # exact
            if s.lower() == v:
                return s
        for s in allowed:                       # containment, either direction
            sl = s.lower()
            if v in sl or sl in v:
                return s
        v_words = {w for w in v.replace("/", " ").replace("-", " ").split() if len(w) > 3}
        for s in allowed:                       # shared significant word
            if v_words & {w for w in s.lower().split() if len(w) > 3}:
                return s
        return default

    def _heuristic(self, text: str) -> dict:
        low = text.lower()
        specialty = next((v for k, v in _SPECIALTY_HINTS.items() if k in low), DEFAULT_SPECIALTY)
        pref = ""
        if "dr." in low or "dr " in low:
            after = low.split("dr")[-1].strip(". ").split()
            if after:
                pref = after[0].capitalize()
        return {"specialty": specialty, "reason": text.strip(), "preferred_provider_name": pref}

    async def execute(self, ctx) -> AgentResult:
        text = ctx.input_data.get("request_text", "")
        allowed = await self._allowed_specialties()
        default = self._default_for(allowed)

        heuristic = self._heuristic(text)
        req = LLMRequest(
            system_prompt=_SYSTEM_TMPL.format(allowed=", ".join(allowed), default=default),
            messages=[LLMMessage.user(text)],
            agent_name=self.name,
            sandbox_response=json.dumps(heuristic),
        )
        resp = await self.llm.complete(req)
        try:
            parsed = json.loads(resp.content)
            if not isinstance(parsed, dict):
                parsed = heuristic
        except (json.JSONDecodeError, TypeError):
            parsed = heuristic

        requested = str(parsed.get("specialty") or heuristic["specialty"] or default)
        specialty = self._snap(requested, allowed, default)
        return AgentResult.completed({
            "specialty": specialty,
            "requested_specialty": requested,
            "specialty_coerced": specialty.lower() != requested.strip().lower(),
            "allowed_specialties": allowed,
            "reason": parsed.get("reason") or text,
            "preferred_provider_name": parsed.get("preferred_provider_name", "") or "",
        })
