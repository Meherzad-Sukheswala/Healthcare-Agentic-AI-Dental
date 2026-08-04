"""
Provider Matcher (single task: pick a provider for the request).

Deterministic (FULL). Uses the NPPES ProviderDirectory port. If a specific NPI was
requested it validates it; otherwise it selects the first specialty match that is
accepting new patients, and also returns the full candidate list for the UI.

Scheduling is the encounter entry point and aborts on failure, so this agent must
not fail on a merely-unlucky specialty. It walks a documented fallback chain and
only fails when the directory has no bookable provider at all. Every downgrade is
reported in `fallback_reason` / `matched_specialty` so the UI and audit log can show
that the patient was not matched to what was literally asked for.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

DEFAULT_SPECIALTY = "General Dentistry"


class ProviderMatcher(Agent):
    name = "provider_matcher"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    @staticmethod
    def _note(existing: str, addition: str) -> str:
        return f"{existing}; {addition}" if existing else addition

    async def execute(self, ctx) -> AgentResult:
        parsed = ctx.get_result("request_parser")
        specialty = parsed.get("specialty") or DEFAULT_SPECIALTY
        preferred = ctx.input_data.get("preferred_provider_npi", "")

        fallback_reason = ""
        matched_specialty = specialty

        if preferred:
            p = await self.reg.directory.get(preferred)
            if p:
                return AgentResult.completed({
                    "selected_npi": p.npi,
                    "provider_name": f"{p.first_name} {p.last_name}",
                    "facility": p.facility,
                    "specialty": p.specialty,
                    "matched_specialty": p.specialty,
                    "requested_specialty": specialty,
                    "fallback_reason": "",
                    "candidates": [p.model_dump()],
                })
            fallback_reason = f"requested provider NPI '{preferred}' not in directory"

        # 1. exactly what was asked for, accepting new patients
        candidates = await self.reg.directory.find(specialty)

        # 2. the default primary-care specialty
        if not candidates and specialty.lower() != DEFAULT_SPECIALTY.lower():
            candidates = await self.reg.directory.find(DEFAULT_SPECIALTY)
            if candidates:
                matched_specialty = DEFAULT_SPECIALTY
                fallback_reason = self._note(
                    fallback_reason,
                    f"no provider accepting new patients for '{specialty}'; "
                    f"routed to {DEFAULT_SPECIALTY}")

        # 3. the asked-for specialty, relaxing the accepting-new-patients filter
        if not candidates:
            candidates = await self.reg.directory.find(specialty, accepting_new=False)
            if candidates:
                matched_specialty = specialty
                fallback_reason = self._note(
                    fallback_reason,
                    f"no '{specialty}' provider accepting new patients; booked with an "
                    f"established-patients-only provider")

        # 4. anyone bookable at all ("" matches every specialty)
        if not candidates:
            candidates = await self.reg.directory.find("", accepting_new=False)
            if candidates:
                matched_specialty = candidates[0].specialty
                fallback_reason = self._note(
                    fallback_reason,
                    f"no match for '{specialty}'; routed to next available provider")

        # 5. genuinely nothing in the directory — a real failure
        if not candidates:
            return AgentResult.failed(
                f"provider directory returned no bookable provider "
                f"(requested specialty '{specialty}')")

        selected = candidates[0]
        return AgentResult.completed({
            "selected_npi": selected.npi,
            "provider_name": f"{selected.first_name} {selected.last_name}",
            "facility": selected.facility,
            "specialty": matched_specialty,
            "matched_specialty": matched_specialty,
            "requested_specialty": specialty,
            "fallback_reason": fallback_reason,
            "candidates": [c.model_dump() for c in candidates],
        })
