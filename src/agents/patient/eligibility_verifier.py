"""
Eligibility Verifier (single task: X12 270/271 coverage check). FULL.

Runs PRE-VISIT, in the scheduling domain — days before the patient arrives, not on
the day of service. That is where a real practice does it, and the ordering is
load-bearing rather than cosmetic: the verified benefit breakdown is what makes the
treatment-plan estimate (and therefore the checkout collection) accurate. Verifying
after the patient is already in the chair would be too late to price the visit.

Identifier resolution mirrors what the front desk actually does, in order:
  1. the booking request, because insurance is captured at booking time — over the
     phone, or from a card photo on the intake link;
  2. the demographics record, if this is driven from inside patient intake;
  3. the insurance already on file in the chart, for a returning patient.

`payer_id` explicitly present but empty means uninsured/self-pay and is honored as
such — only an ABSENT payer_id falls through to the chart.

Real-world caveat this does NOT model: the 271 comes back with coverage categories
and remaining maximum, but usually not the procedure-level detail an estimate needs.
Frequency limits, waiting periods, and downgrade clauses still take a payer-portal
lookup or a phone call. See docs/us-dental-clinic-real-world-workflow.md §3.5.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class EligibilityVerifier(Agent):
    name = "eligibility_verifier"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def _on_file(self, ctx) -> dict:
        """Insurance already in the chart, for a returning patient."""
        rec = await self.reg.ehr.get_patient(ctx.input_data.get("patient_id", ""))
        return rec.model_dump() if rec is not None else {}

    async def execute(self, ctx) -> AgentResult:
        demo = ctx.get_result("demographics_intake")
        payer_id = ctx.input_data.get("payer_id")
        member_id = ctx.input_data.get("member_id")

        if payer_id is None:                      # absent, not "explicitly uninsured"
            payer_id = demo.get("payer_id")
            member_id = member_id if member_id is not None else demo.get("member_id")
        if payer_id is None:
            on_file = await self._on_file(ctx)
            payer_id = on_file.get("payer_id", "")
            member_id = member_id if member_id is not None else on_file.get("member_id", "")

        payer_id, member_id = payer_id or "", member_id or ""
        cov = await self.reg.eligibility.check(member_id, payer_id, "D0140")
        return AgentResult.completed({
            "coverage": cov.model_dump(),
            "verified_pre_visit": True,
            "member_id": member_id,
            "payer_id": payer_id,
        })
