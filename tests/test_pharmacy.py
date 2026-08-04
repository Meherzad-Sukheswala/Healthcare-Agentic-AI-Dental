"""Pharmacy domain: pharmacist gate, allergy hard stop, PDMP for controlled, DUR duplicate."""
from src.agents.pharmacy import PharmacyOrchestrator
from src.config import Settings
from src.core.llm import LLMClient
from src.core.orchestrator import GateDecision, PipelineContext
from src.integrations import build_registry
from src.shared.enums import PipelineStatus


def _orch():
    s = Settings(_env_file=None)
    return PharmacyOrchestrator(registry=build_registry(s), llm_client=LLMClient(s))


def _in(prescribe, allergies=None, current=None):
    return {
        "patient_id": "PAT-001", "state": "CA", "pharmacy_id": "PHARM-001",
        "allergies": allergies or [], "current_medications": current or [],
        "prescriptions": prescribe,
    }


RX_ACETAMINOPHEN = [{"rx_id": "RX-1", "rxcui": "161", "ndc": "0069-2587-10", "controlled": False}]
RX_OXYCODONE = [{"rx_id": "RX-2", "rxcui": "7804", "ndc": "0069-2587-10", "controlled": True}]
RX_AMOX = [{"rx_id": "RX-3", "rxcui": "723", "ndc": "0069-2587-10", "controlled": False}]


def _verify():
    return GateDecision(gate_id="pharmacy.verification", approved=True, actor="PharmD Lee")


async def test_pharmacist_gate_then_dispense():
    paused = await _orch().run(PipelineContext(encounter_id="P1", input_data=_in(RX_ACETAMINOPHEN)))
    assert paused.gate.gate_id == "pharmacy.verification"

    ctx = PipelineContext(encounter_id="P1", input_data=_in(RX_ACETAMINOPHEN))
    ctx.add_decision(_verify())
    done = await _orch().run(ctx)
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["dispensed"] is True
    assert done.output["dispatch"]["dispatched"] is True
    assert done.output["pdmp"]["queried"] is False        # non-controlled


async def test_controlled_triggers_pdmp():
    ctx = PipelineContext(encounter_id="P2", input_data=_in(RX_OXYCODONE))
    ctx.add_decision(_verify())
    done = await _orch().run(ctx)
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["pdmp"]["queried"] is True
    assert done.output["dispensed"] is True


async def test_allergy_hard_stop_blocks_dispense():
    ctx = PipelineContext(encounter_id="P3", input_data=_in(RX_AMOX, allergies=["penicillin"]))
    ctx.add_decision(_verify())
    done = await _orch().run(ctx)
    assert done.output["allergy_gate_passed"] is False
    assert done.output["dispensed"] is False              # hard stop skips dispensing


async def test_dur_flags_duplicate_therapy():
    ctx = PipelineContext(encounter_id="P4", input_data=_in(RX_ACETAMINOPHEN, current=["161"]))
    ctx.add_decision(_verify())
    done = await _orch().run(ctx)
    assert done.output["dur"]["dur_flagged"] is True       # acetaminophen already active
