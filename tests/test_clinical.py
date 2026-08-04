"""Clinical domain: diagnosis sign-off, treatment planning, EPCS gate, critical-value gate, allergy screen."""
from src.agents.clinical import ClinicalOrchestrator
from src.config import Settings
from src.core.llm import LLMClient
from src.core.orchestrator import GateDecision, PipelineContext
from src.integrations import build_registry
from src.integrations.seed_data import PROVIDERS
from src.shared.enums import PipelineStatus

NPI = PROVIDERS[0].npi


def _orch():
    s = Settings(_env_file=None)
    return ClinicalOrchestrator(registry=build_registry(s), llm_client=LLMClient(s))


def _base(**over):
    data = {
        "patient_id": "PAT-001",
        "selected_npi": NPI,
        "chief_complaint": "tooth pain and swelling",
        "current_medications": ["11289"],
        "allergies": ["penicillin"],
        "prescribe": [{"rxcui": "161", "display": "acetaminophen", "ndc": "0069-2587-10", "schedule": "non_controlled"}],
        "coverage": {"active": True, "annual_max_cents": 150000, "annual_max_used_cents": 0,
                     "category_coverage_pct": {"preventive": 1.0, "basic": 0.8, "major": 0.5}},
    }
    data.update(over)
    return data


def _dx(note=""):
    return GateDecision(gate_id="clinical.diagnosis", approved=True, actor="Dr. Rao, MD", note=note)


def _tx_review(note=""):
    return GateDecision(gate_id="clinical.treatment_plan", approved=True, actor="Dr. Rao, MD", note=note)


def _tx_consent(note=""):
    return GateDecision(gate_id="clinical.treatment_consent", approved=True, actor="Maria Garcia", note=note)


def _ctx(eid, data, *decisions):
    ctx = PipelineContext(encounter_id=eid, input_data=dict(data))
    for d in decisions:
        ctx.add_decision(d)
    return ctx


async def test_diagnosis_gate_then_complete():
    data = _base()
    paused = await _orch().run(_ctx("C1", data))
    assert paused.gate.gate_id == "clinical.diagnosis"

    paused2 = await _orch().run(_ctx("C1", data, _dx()))
    assert paused2.gate.gate_id == "clinical.treatment_plan"
    assert paused2.gate.data["items"][0]["cdt"] == "D3330"      # root canal recommended first

    paused3 = await _orch().run(_ctx("C1", data, _dx(), _tx_review()))
    assert paused3.gate.gate_id == "clinical.treatment_consent"
    assert paused3.gate.data["estimated_patient_cents"] > 0

    done = await _orch().run(_ctx("C1", data, _dx(), _tx_review(), _tx_consent()))
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["icd10"] == "K04.7"
    assert done.output["cdt"] == "D3330"                        # billed procedure, not just an eval code
    assert "D2740" in done.output["cdt_codes"]                  # crown — phase 3, same plan
    assert done.output["document_ref"]
    assert done.output["interactions"]["unsafe"] is False


async def test_patient_can_decline_part_of_phased_treatment_plan():
    """The crown (TX2) can be deferred while the root canal (TX1) proceeds today."""
    data = _base()
    done = await _orch().run(_ctx("C5", data, _dx(), _tx_review(), _tx_consent(note="TX2")))
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["cdt_codes"] == ["D3330"]
    assert done.output["treatment_consent"]["declined_item_ids"] == ["TX2"]


async def test_routine_visit_with_no_findings_skips_treatment_plan_gates():
    """K08.9 (the fallback diagnosis) has no procedure map entry — exam only, no new gates."""
    data = _base(chief_complaint="annual checkup")
    done = await _orch().run(_ctx("C6", data, _dx()))
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["cdt"] in ("D0140", "D0150")             # falls back to the eval code


async def test_controlled_rx_hits_epcs_gate_and_signs():
    data = _base(prescribe=[{"rxcui": "7804", "display": "oxycodone", "ndc": "0069-2587-10", "schedule": "CII"}])
    paused = await _orch().run(_ctx("C2", data, _dx(), _tx_review(), _tx_consent()))
    assert paused.gate.gate_id == "clinical.epcs"

    epcs = GateDecision(gate_id="clinical.epcs", approved=True, actor="Dr. Rao, MD", note="654321")
    done = await _orch().run(_ctx("C2", data, _dx(), _tx_review(), _tx_consent(), epcs))
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["epcs"]["signed"] is True
    assert done.output["epcs"]["two_factor_used"] is True


async def test_critical_value_gate_fires_first():
    data = _base(labs={"potassium": 6.5}, prescribe=[])
    paused = await _orch().run(_ctx("C3", data))
    assert paused.gate.gate_id == "clinical.critical_value"

    cv = GateDecision(gate_id="clinical.critical_value", approved=True, actor="RN Adams")
    done = await _orch().run(_ctx("C3", data, cv, _dx(), _tx_review(), _tx_consent()))
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["critical"]["has_critical"] is True


async def test_allergy_conflict_detected():
    data = _base(prescribe=[{"rxcui": "723", "display": "amoxicillin", "ndc": "0069-2587-10", "schedule": "non_controlled"}])
    done = await _orch().run(_ctx("C4", data, _dx(), _tx_review(), _tx_consent()))
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["allergy"]["has_conflict"] is True     # amoxicillin vs penicillin allergy
