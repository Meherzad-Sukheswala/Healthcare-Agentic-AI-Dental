"""
The human-gate pause/resume primitive and the DomainOrchestrator engine.

Builds a tiny 3-agent domain (compute -> human gate -> finalize) and proves:
  * with no decision, the pipeline PAUSES at the gate and surfaces a GateRequest
  * re-running with an approval RESUMES and completes
  * a rejection is handled as a non-completing outcome
"""
import pytest

from src.core.orchestrator import (
    Agent,
    AgentResult,
    DomainOrchestrator,
    GateDecision,
    GateRequest,
    HumanGateAgent,
    PipelineContext,
    PipelineStep,
)
from src.shared.enums import Automation, PipelineStatus


class ComputeAgent(Agent):
    name = "compute"
    automation = Automation.FULL

    async def execute(self, ctx: PipelineContext) -> AgentResult:
        return AgentResult.completed({"value": ctx.input_data.get("x", 0) + 1})


class ApprovalGate(HumanGateAgent):
    name = "approval_gate"
    gate_id = "demo.approval"

    def build_request(self, ctx: PipelineContext) -> GateRequest:
        return GateRequest(
            gate_id=self.gate_id, title="Approve value", prompt="OK?",
            domain="demo", data={"value": ctx.get_result("compute").get("value")},
        )

    def on_approved(self, ctx, decision):
        return {"approved_by": decision.actor, "value": ctx.get_result("compute").get("value")}


class FinalizeAgent(Agent):
    name = "finalize"

    async def execute(self, ctx: PipelineContext) -> AgentResult:
        return AgentResult.completed({"final": ctx.get_result("compute").get("value", 0) * 10})


class DemoDomain(DomainOrchestrator):
    name = "demo"

    def build_steps(self):
        return [PipelineStep(ComputeAgent()), PipelineStep(ApprovalGate()), PipelineStep(FinalizeAgent())]

    def build_output(self, ctx):
        return {"final": ctx.get_result("finalize").get("final"),
                "value": ctx.get_result("compute").get("value")}


async def test_pauses_at_gate():
    ctx = PipelineContext(encounter_id="E1", input_data={"x": 4})
    res = await DemoDomain().run(ctx)
    assert res.status == PipelineStatus.AWAITING_HUMAN
    assert res.gate is not None and res.gate.gate_id == "demo.approval"
    assert res.gate.data["value"] == 5
    assert "finalize" not in res.executed


async def test_resumes_on_approval():
    ctx = PipelineContext(encounter_id="E1", input_data={"x": 4})
    ctx.add_decision(GateDecision(gate_id="demo.approval", approved=True, actor="Dr. Rao"))
    res = await DemoDomain().run(ctx)
    assert res.status == PipelineStatus.COMPLETED
    assert res.output["final"] == 50
    assert "finalize" in res.executed


async def test_rejection_stops_completion():
    ctx = PipelineContext(encounter_id="E1", input_data={"x": 4})
    ctx.add_decision(GateDecision(gate_id="demo.approval", approved=False, actor="Dr. Rao", note="no"))
    res = await DemoDomain().run(ctx)
    assert res.status != PipelineStatus.COMPLETED
    assert res.errors
