"""
Charge / Coding QA (single task: pre-submission coder/CDI review). MANUAL.

Runs for high-cost or complex encounters (a CDI/coder confirms codes before the
patient is billed). Conditional so routine visits are not gated.
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent

# encounters at/above this charge get a mandatory coding review
QA_THRESHOLD_CENTS = 100000


class ChargeCodingQA(HumanGateAgent):
    name = "charge_coding_qa"
    gate_id = "billing.coding_qa"

    def build_request(self, ctx) -> GateRequest:
        return GateRequest(
            gate_id=self.gate_id,
            title="Coding / charge QA review",
            prompt="CDI/coder: verify diagnosis & procedure codes before billing.",
            domain="billing",
            data={"total_cents": ctx.get_result("bill_splitter").get("total_cents", 0),
                  "icd10": ctx.input_data.get("icd10", ""), "cdt": ctx.input_data.get("cdt", "")},
        )

    def on_approved(self, ctx, decision) -> dict:
        return {"coding_qa_passed": True, "reviewer": decision.actor}
