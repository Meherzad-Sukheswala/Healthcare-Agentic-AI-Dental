"""Alert Generator (single task: raise an SIU alert above threshold). FULL."""
from __future__ import annotations

import hashlib

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

ALERT_THRESHOLD = 25          # risk score at/above which an alert is queued


class AlertGenerator(Agent):
    name = "alert_generator"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        risk = ctx.get_result("risk_scorer")
        score = risk.get("risk_score", 0)
        if score < ALERT_THRESHOLD:
            return AgentResult.completed({"alert": False})
        alert_id = "ALERT-" + hashlib.sha256(
            f"{ctx.encounter_id}{score}".encode()).hexdigest()[:8].upper()
        return AgentResult.completed({
            "alert": True, "alert_id": alert_id, "risk_score": score,
            "level": risk.get("level"), "signals": risk.get("signals", []),
            "queue": "siu_review",
        })
