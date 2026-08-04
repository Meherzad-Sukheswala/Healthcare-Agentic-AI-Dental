"""
Triage Classifier (single task: assign an urgency level).

Deterministic rules over the parsed reason. Routine requests continue automatically;
urgent/emergent are flagged so a nurse can intervene (PARTIAL — human oversight on
the exception path). Kept rule-based for reliability during a live demo.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation, TriageLevel

_RED_FLAGS = (
    "crushing chest pain", "chest pain radiating", "shortness of breath", "can't breathe",
    "stroke", "face droop", "slurred speech", "suicidal", "severe bleeding", "anaphylaxis",
    "unconscious", "worst headache",
)
_URGENT = ("severe", "acute", "high fever", "fever of", "worsening", "sudden")


class TriageClassifier(Agent):
    name = "triage_classifier"
    automation = Automation.PARTIAL

    async def execute(self, ctx) -> AgentResult:
        reason = (ctx.get_result("request_parser").get("reason")
                  or ctx.input_data.get("request_text", "")).lower()
        if any(flag in reason for flag in _RED_FLAGS):
            level = TriageLevel.EMERGENT
        elif any(term in reason for term in _URGENT):
            level = TriageLevel.URGENT
        else:
            level = TriageLevel.ROUTINE
        return AgentResult.completed({
            "triage_level": level.value,
            "requires_human_triage": level != TriageLevel.ROUTINE,
        })
