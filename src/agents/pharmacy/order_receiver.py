"""
Order Receiver (single task: receive the e-prescription at the target pharmacy). FULL.

The script routes to a single, patient-chosen pharmacy (as Surescripts works in
reality) — there is no universal cross-pharmacy inventory to shop against.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class OrderReceiver(Agent):
    name = "order_receiver"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        prescriptions = ctx.input_data.get("prescriptions", []) or []
        pharmacy_id = ctx.input_data.get("pharmacy_id", "PHARM-001")
        order = {"patient_id": ctx.input_data.get("patient_id", ""), "pharmacy_id": pharmacy_id,
                 "items": [{"rx_id": p.get("rx_id"), "rxcui": p.get("rxcui"), "ndc": p.get("ndc"),
                            "controlled": p.get("controlled", False)} for p in prescriptions]}
        order_id = await self.reg.pharmacy.send_prescription(order)
        return AgentResult.completed({"order_id": order_id, "pharmacy_id": pharmacy_id, "items": order["items"]})
