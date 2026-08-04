"""
Procedure Documentor (single task: record what was actually billable today). FULL.

Replaces the old "guess an eval code from symptom count" heuristic. The CDT code(s)
that go on the claim now come from what the patient actually consented to and the
dentist actually performed — the treatment plan's accepted line items — not a proxy.
An exam-only visit (nothing proposed, or nothing accepted) still falls back to
billing the evaluation code, exactly as before.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation
from src.shared.medical_codes import is_valid_cdt

_EXAM_FEE = {"D0140": 9500, "D0150": 15000}


class ProcedureDocumentor(Agent):
    name = "procedure_documentor"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        plan_items = ctx.get_result("treatment_plan_builder").get("items", [])
        consent = ctx.get_result("treatment_plan_consent")
        accepted_ids = consent.get("accepted_item_ids") if consent else None

        if plan_items and accepted_ids is not None:
            performed = [dict(i, status="completed") for i in plan_items if i["item_id"] in accepted_ids]
        else:
            performed = []

        if not performed:
            symptoms = len(ctx.get_result("symptom_recorder").get("symptoms", []))
            rx = len(ctx.get_result("prescription_drafter").get("prescriptions", [])) if \
                ctx.get_result("prescription_drafter") else 0
            cdt = "D0150" if (symptoms >= 3 or rx >= 2) else "D0140"
            performed = [{"item_id": "EXAM", "tooth": "", "cdt": cdt,
                         "description": "Oral evaluation", "phase": "diagnostic",
                         "fee_cents": _EXAM_FEE[cdt], "status": "completed"}]

        codes = [i["cdt"] for i in performed]
        return AgentResult.completed({
            "performed_items": performed,
            "cdt_codes": codes,
            "cdt": codes[0] if codes else "D0140",   # primary code — backward-compat single-value key
            "total_cents": sum(i["fee_cents"] for i in performed),
            "valid": all(is_valid_cdt(c) for c in codes),
        })
