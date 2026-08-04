"""Billing Anomaly Detector (single task: billing outliers). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

_OUTLIER_CENTS = 200000        # $2,000 charge outlier threshold


class BillingAnomalyDetector(Agent):
    name = "billing_anomaly_detector"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        charge = int(ctx.input_data.get("charge_cents", 0))
        signals, points = [], 0
        if charge >= _OUTLIER_CENTS:
            signals.append("high_charge_outlier")
            points += 20
        if ctx.input_data.get("duplicate_claim"):
            signals.append("duplicate_claim")
            points += 25
        return AgentResult.completed({"signals": signals, "risk_points": points})
