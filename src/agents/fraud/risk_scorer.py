"""Risk Scorer (single task: aggregate signals into a 0-100 risk score). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

_SOURCES = ("claim_analyzer", "prescription_analyzer", "billing_anomaly_detector", "consistency_checker")


class RiskScorer(Agent):
    name = "risk_scorer"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        total, signals = 0, []
        for src in _SOURCES:
            r = ctx.get_result(src)
            total += int(r.get("risk_points", 0))
            signals.extend(r.get("signals", []))
        score = min(total, 100)
        level = "high" if score >= 50 else "medium" if score >= 25 else "low"
        return AgentResult.completed({"risk_score": score, "level": level, "signals": signals})
