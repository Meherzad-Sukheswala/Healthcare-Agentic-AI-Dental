"""
Controlled-Rx EPCS Signer (single task: DEA EPCS 2-factor signing). MANUAL.

Runs only when a controlled substance was drafted. This gate is special: after the
prescriber approves, it performs the actual 2-factor signing via the EPCS port
(the decision note carries the one-time second factor). Overrides execute() so the
signing call can be awaited.
"""
from __future__ import annotations

from src.core.orchestrator import AgentResult, GateRequest, HumanGateAgent


class ControlledRxEPCSSigner(HumanGateAgent):
    name = "controlled_rx_epcs_signer"
    gate_id = "clinical.epcs"

    def __init__(self, registry):
        self.reg = registry

    def build_request(self, ctx) -> GateRequest:
        controlled = [p for p in ctx.get_result("prescription_drafter").get("prescriptions", [])
                      if p.get("controlled")]
        return GateRequest(
            gate_id=self.gate_id,
            title="Controlled substance — EPCS signing required",
            prompt="Authenticate with your second factor (enter OTP in the note) to sign.",
            domain="clinical",
            data={"prescriptions": controlled, "prescriber_npi": ctx.input_data.get("selected_npi", "")},
        )

    async def execute(self, ctx) -> AgentResult:
        decision = ctx.decision_for(self.gate_id)
        if decision is None:
            return AgentResult.awaiting(self.build_request(ctx))
        if not decision.approved:
            return AgentResult.rejected(self.gate_id, decision.note)

        controlled = [p for p in ctx.get_result("prescription_drafter").get("prescriptions", [])
                      if p.get("controlled")]
        npi = ctx.input_data.get("selected_npi", "")
        otp = decision.note or ""                      # second factor
        rx_id = controlled[0]["rx_id"] if controlled else "RX-UNKNOWN"
        sig = await self.reg.epcs.sign(npi, rx_id, otp)
        if not sig.signed:
            return AgentResult.failed("EPCS signing failed: invalid second factor")
        return AgentResult.completed({
            "epcs_signature_id": sig.signature_id,
            "signed": True,
            "two_factor_used": sig.two_factor_used,
            "signed_by": decision.actor,
            "signed_rx_ids": [p["rx_id"] for p in controlled],
        })
