"""Patient domain: consent gate, MPI gate, multi-gate compose, and abort."""
from src.agents.patient import PatientOrchestrator
from src.config import Settings
from src.core.llm import LLMClient
from src.core.orchestrator import GateDecision, PipelineContext
from src.integrations import build_registry
from src.shared.enums import PipelineStatus


def _orch():
    s = Settings(_env_file=None)
    return PatientOrchestrator(registry=build_registry(s), llm_client=LLMClient(s))


async def test_pauses_at_consent_then_completes():
    data = {"patient_id": "PAT-001"}
    paused = await _orch().run(PipelineContext(encounter_id="R1", input_data=dict(data)))
    assert paused.status == PipelineStatus.AWAITING_HUMAN
    assert paused.gate.gate_id == "patient.consent"

    ctx = PipelineContext(encounter_id="R1", input_data=dict(data))
    ctx.add_decision(GateDecision(gate_id="patient.consent", approved=True, actor="Maria Garcia"))
    done = await _orch().run(ctx)
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["consent"]["consent_status"] == "signed"
    assert done.output["identity"]["ambiguous"] is False
    # eligibility is NOT verified here — it moved to the pre-visit (scheduling) domain,
    # because a coverage check on the day of service is too late to price the visit.
    # See test_scheduling.py::test_eligibility_is_verified_pre_visit.
    assert "coverage" not in done.output


async def test_ambiguous_identity_hits_mpi_gate_first():
    data = {"patient_id": "PAT-001", "identity_ambiguous": True}
    paused = await _orch().run(PipelineContext(encounter_id="R2", input_data=dict(data)))
    assert paused.gate.gate_id == "patient.mpi"           # MPI gate precedes consent

    # supply BOTH decisions -> full completion in one resumed run
    ctx = PipelineContext(encounter_id="R2", input_data=dict(data))
    ctx.add_decision(GateDecision(gate_id="patient.mpi", approved=True, actor="MPI Steward"))
    ctx.add_decision(GateDecision(gate_id="patient.consent", approved=True, actor="Maria Garcia"))
    done = await _orch().run(ctx)
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["consent"]["consent_status"] == "signed"


async def test_unknown_patient_aborts():
    res = await _orch().run(PipelineContext(encounter_id="R3", input_data={"patient_id": "PAT-999"}))
    assert res.status == PipelineStatus.FAILED
    assert res.errors
