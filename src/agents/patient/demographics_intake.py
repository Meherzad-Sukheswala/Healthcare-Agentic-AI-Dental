"""Demographics Intake (single task: fetch the patient record from the EHR). FULL."""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class DemographicsIntake(Agent):
    name = "demographics_intake"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        pid = ctx.input_data.get("patient_id", "")
        rec = await self.reg.ehr.get_patient(pid)
        if rec is None:
            return AgentResult.failed(f"patient {pid!r} not found in EHR")
        data = rec.model_dump()
        # Optional runtime insurance override (drives eligibility downstream).
        # payer_id == "" (with member "") => uninsured/self-pay; a PAYER-* => that plan.
        override_payer = ctx.input_data.get("override_payer_id")
        if override_payer is not None:
            data["payer_id"] = override_payer
            override_member = ctx.input_data.get("override_member_id")
            data["member_id"] = override_member if override_member is not None else data.get("member_id", "")
        return AgentResult.completed(data)
