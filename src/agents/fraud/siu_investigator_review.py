"""
SIU Investigator Review (single task: human fraud review). MANUAL — but NON-BLOCKING.

This is a mandated human touchpoint, yet fraud detection is a parallel observer that
must NEVER block care or billing. So unlike the other 11 gates, this one does not
pause the pipeline: if an alert exists and no decision is present, it simply queues
the case for out-of-band SIU review and completes. A later decision (approved = case
cleared / legitimate; rejected = confirmed fraud) is applied when the fraud domain is
re-run against the queue.
"""
from __future__ import annotations

from src.core.orchestrator import AgentResult, GateRequest, HumanGateAgent


class SIUInvestigatorReview(HumanGateAgent):
    name = "siu_investigator_review"
    gate_id = "fraud.siu"

    def build_request(self, ctx) -> GateRequest:
        alert = ctx.get_result("alert_generator")
        return GateRequest(
            gate_id=self.gate_id, title="SIU fraud review", prompt="Investigate flagged encounter.",
            domain="fraud", data={"alert_id": alert.get("alert_id", ""), "signals": alert.get("signals", [])},
        )

    async def execute(self, ctx) -> AgentResult:
        if not ctx.get_result("alert_generator").get("alert", False):
            return AgentResult.completed({"siu_status": "no_alert"})
        decision = ctx.decision_for(self.gate_id)
        if decision is None:
            # queue for out-of-band review — DO NOT pause the pipeline
            return AgentResult.completed({"siu_status": "pending_review", "queued": True})
        return AgentResult.completed({
            "siu_status": "cleared" if decision.approved else "confirmed_fraud",
            "reviewer": decision.actor,
        })
