"""Prescription Analyzer (single task: fraud signals in prescriptions). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class PrescriptionAnalyzer(Agent):
    name = "prescription_analyzer"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        prescriptions = ctx.input_data.get("prescriptions", []) or []
        pdmp_flags = ctx.input_data.get("pdmp_risk_flags", []) or []
        controlled = any(p.get("controlled") for p in prescriptions)
        signals, points = [], 0
        if controlled and pdmp_flags:
            signals.append("controlled_with_pdmp_risk")
            points += 30
        if "multiple_prescribers" in pdmp_flags:
            signals.append("multiple_prescribers")
            points += 10
        return AgentResult.completed({"signals": signals, "risk_points": points})
