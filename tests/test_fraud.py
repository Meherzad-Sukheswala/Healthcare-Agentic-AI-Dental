"""Fraud domain: clean pass, high-risk alert, SIU review — and NEVER blocks."""
from src.agents.fraud import FraudDetectionOrchestrator
from src.config import Settings
from src.core.llm import LLMClient
from src.core.orchestrator import GateDecision, PipelineContext
from src.integrations import build_registry
from src.shared.enums import PipelineStatus


def _orch():
    s = Settings(_env_file=None)
    return FraudDetectionOrchestrator(registry=build_registry(s), llm_client=LLMClient(s))


CLEAN = {"cdt": "D0140", "charge_cents": 15000, "diagnosis_icd10": "I10",
         "prescriptions": [{"rxcui": "29046", "controlled": False}], "pdmp_risk_flags": []}

FRAUDY = {"cdt": "D0150", "charge_cents": 250000, "diagnosis_icd10": "I48.91",
          "prescriptions": [{"rxcui": "7804", "controlled": True}],
          "pdmp_risk_flags": ["multiple_prescribers", "frequent_controlled_fills"]}


async def test_clean_encounter_no_alert():
    res = await _orch().run(PipelineContext(encounter_id="F1", input_data=dict(CLEAN)))
    assert res.status == PipelineStatus.COMPLETED
    assert res.output["pipeline_blocked"] is False
    assert res.output["level"] == "low"
    assert res.output["alert"] is False
    assert res.output["siu"]["siu_status"] == "no_alert"


async def test_high_risk_alerts_but_never_blocks():
    res = await _orch().run(PipelineContext(encounter_id="F2", input_data=dict(FRAUDY)))
    # ABSOLUTE rule: fraud never pauses or blocks the pipeline
    assert res.status == PipelineStatus.COMPLETED
    assert res.status != PipelineStatus.AWAITING_HUMAN
    assert res.output["pipeline_blocked"] is False
    assert res.output["alert"] is True
    assert res.output["level"] == "high"
    assert res.output["siu"]["siu_status"] == "pending_review"     # queued, not blocking


async def test_siu_decision_applied_out_of_band():
    ctx = PipelineContext(encounter_id="F2", input_data=dict(FRAUDY))
    ctx.add_decision(GateDecision(gate_id="fraud.siu", approved=False, actor="SIU Agent"))
    res = await _orch().run(ctx)
    assert res.output["pipeline_blocked"] is False
    assert res.output["siu"]["siu_status"] == "confirmed_fraud"


async def test_consistency_mismatch_adds_risk():
    data = {"cdt": "D0140", "charge_cents": 15000, "diagnosis_icd10": "I10",
            "prescriptions": [{"rxcui": "11289", "controlled": False}], "pdmp_risk_flags": []}
    res = await _orch().run(PipelineContext(encounter_id="F3", input_data=data))
    assert res.output["consistency"]["consistent"] is False        # warfarin atypical for HTN
    assert res.output["risk_score"] >= 25


async def test_dental_consistency_mismatch_adds_risk():
    """Dental presenting diagnoses must be covered by the plausibility map too —
    not just the legacy medical-history codes (I10/I48/E78)."""
    data = {"cdt": "D0140", "charge_cents": 15000, "diagnosis_icd10": "M26.60",
            "prescriptions": [{"rxcui": "723", "controlled": False}], "pdmp_risk_flags": []}
    res = await _orch().run(PipelineContext(encounter_id="F4", input_data=data))
    assert res.output["consistency"]["consistent"] is False        # amoxicillin atypical for TMJ disorder
    assert res.output["risk_score"] >= 25


async def test_dental_consistency_match_is_clean():
    data = {"cdt": "D0140", "charge_cents": 15000, "diagnosis_icd10": "K04.7",
            "prescriptions": [{"rxcui": "723", "controlled": False}], "pdmp_risk_flags": []}
    res = await _orch().run(PipelineContext(encounter_id="F5", input_data=data))
    assert res.output["consistency"]["consistent"] is True         # amoxicillin is plausible for an abscess
    assert res.output["alert"] is False


async def test_duplicate_procedure_on_one_claim_flagged():
    """The same CDT code billed twice on one claim is a real, well-documented
    duplicate-billing pattern — now that claims can carry multiple service lines,
    the analyzer has to actually look at all of them, not just the primary code."""
    data = {"cdt": "D3330", "cdt_codes": ["D3330", "D3330"], "charge_cents": 15000,
            "diagnosis_icd10": "K04.7", "prescriptions": [], "pdmp_risk_flags": []}
    res = await _orch().run(PipelineContext(encounter_id="F6", input_data=data))
    assert "duplicate_procedure_billing" in res.output["signals"]
