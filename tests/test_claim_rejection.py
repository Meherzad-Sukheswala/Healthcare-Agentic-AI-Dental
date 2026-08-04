"""
The REJECTION half of the claim cycle: front-end edits bounce a claim before any payer
adjudicates it.

The thing these tests protect is the distinction itself. A rejection has no CARC codes,
is not appealable, and is fixed by correcting a data element and resubmitting as a
replacement claim. Routing one to the appeal gate burns a 30-90 day cycle on something
fixable in an afternoon, so the two paths must not converge.
"""
import pytest

from src.agents.insurance import InsuranceOrchestrator
from src.config import Settings
from src.core.llm import LLMClient
from src.core.orchestrator import GateDecision, PipelineContext
from src.integrations import build_registry
from src.integrations.seed_data import PROVIDERS
from src.shared.claim_scrubber import scrub_claim
from src.shared.enums import PipelineStatus

NPI = PROVIDERS[0].npi


def _orch():
    s = Settings(_env_file=None)
    return InsuranceOrchestrator(registry=build_registry(s), llm_client=LLMClient(s))


def _performed(cdt="D3330", tooth="19", fee=145000):
    return [{"item_id": "TX1", "cdt": cdt, "tooth": tooth, "fee_cents": fee,
             "description": "Endodontic therapy", "phase": "phase1", "status": "completed"}]


def _in(**over):
    data = {"member_id": "BCB-90001", "payer_id": "PAYER-001", "cdt": "D3330",
            "icd10": "K04.7", "tooth": "19", "provider_npi": NPI,
            "performed_items": _performed(),
            "diagnosis_codes": ["K04.7"],
            "line_diagnoses": [{"item_id": "TX1", "cdt": "D3330", "tooth": "19",
                                "icd10": "K04.7", "diagnosis_pointer": "A"}],
            # endo warrants records, so the payer pends; these are on file, letting the AI
            # answer without a human. The pend paths are covered in test_information_request.py
            "document_registry": {
                "preop_radiograph": {"available": True, "count": 1, "detail": "PA #19 pre-op"},
                "postop_radiograph": {"available": True, "count": 1, "detail": "PA #19 post-op"},
            },
            "ndcs": []}
    data.update(over)
    return data


def _claim(**over):
    """A clean 837D, for scrubber unit tests."""
    claim = {"member_id": "BCB-90001", "payer_id": "PAYER-001", "billing_npi": NPI,
             "diagnosis_codes": ["K04.7"],
             "service_lines": [{"cdt": "D3330", "tooth": "19", "charge_cents": 145000,
                                "diagnosis_pointer": "A"}]}
    claim.update(over)
    return claim


# ----------------------------------------------------------------- the scrubber
def test_clean_claim_passes_every_front_end_edit():
    assert scrub_claim(_claim()) == []


@pytest.mark.parametrize("field,value,category,status_code", [
    ("member_id", "", "A6", "164"),          # missing information
    ("payer_id", "", "A7", "116"),           # invalid information
    ("billing_npi", "", "A6", "562"),        # missing NPI
    ("billing_npi", "1234567890", "A7", "562"),  # NPI fails the CMS Luhn check digit
])
def test_identity_faults_are_rejected_with_the_right_category(field, value, category, status_code):
    problems = scrub_claim(_claim(**{field: value}))
    assert len(problems) == 1
    assert problems[0]["category_code"] == category
    assert problems[0]["status_code"] == status_code
    # a rejection a biller cannot locate is a rejection they cannot fix
    assert problems[0]["element"]
    assert problems[0]["fix_hint"]


def test_tooth_specific_code_without_a_tooth_is_a_relational_rejection():
    """D3330 is endodontic therapy — it cannot be adjudicated without knowing which
    tooth. That is a relational error (A8): the field is wrong GIVEN another field."""
    problems = scrub_claim(_claim(service_lines=[
        {"cdt": "D3330", "tooth": "", "charge_cents": 145000, "diagnosis_pointer": "A"}]))
    assert [p["category_code"] for p in problems] == ["A8"]
    assert "Tooth number is required" in problems[0]["description"]


def test_quadrant_level_code_does_not_need_a_tooth():
    """Scaling and root planing is billed per quadrant, so a blank tooth is correct and
    must not be flagged — over-scrubbing would block legitimate perio claims."""
    assert scrub_claim(_claim(service_lines=[
        {"cdt": "D4341", "tooth": "", "charge_cents": 32000, "diagnosis_pointer": "A"}])) == []


def test_zero_charge_line_is_out_of_balance():
    problems = scrub_claim(_claim(service_lines=[
        {"cdt": "D3330", "tooth": "19", "charge_cents": 0, "diagnosis_pointer": "A"}]))
    assert any(p["status_code"] == "400" for p in problems)


def test_payer_specific_edit_only_fires_for_payers_that_require_a_diagnosis():
    """Medicare rejects dental claims with no valid ICD-10; commercial plans adjudicate
    on CDT and must not be held to the same edit."""
    no_dx = _claim(diagnosis_codes=[])
    assert scrub_claim(no_dx, {"requires_diagnosis_codes": False}) == []

    problems = scrub_claim(no_dx, {"requires_diagnosis_codes": True})
    assert [p["status_code"] for p in problems] == ["255"]
    assert problems[0]["category_code"] == "A6"


def test_missing_diagnosis_pointer_is_relational_not_missing_info():
    """The codes are present but no line points at them — that is A8, not A6."""
    problems = scrub_claim(
        _claim(service_lines=[{"cdt": "D3330", "tooth": "19", "charge_cents": 145000,
                               "diagnosis_pointer": ""}]),
        {"requires_diagnosis_codes": True})
    assert [(p["category_code"], p["status_code"]) for p in problems] == [("A8", "255")]


# ------------------------------------------------------- the rejection branch
async def test_clean_claim_is_accepted_and_gets_a_remittance():
    res = await _orch().run(PipelineContext(encounter_id="R1", input_data=_in()))
    assert res.status == PipelineStatus.COMPLETED
    ack = res.output["claim_ack"]
    assert ack["accepted"] is True
    assert ack["status"] == "accepted"
    assert ack["transaction"] == "277CA"
    assert ack["payer_receipt_date"]          # the timely-filing anchor
    assert res.output["claim_rejected"] is False
    assert res.output["remittance"]["billed_cents"] == 145000


async def test_rejected_claim_opens_the_rejection_gate_not_the_appeal_gate():
    paused = await _orch().run(PipelineContext(
        encounter_id="R2", input_data=_in(claim_defect="member_id")))
    assert paused.status == PipelineStatus.AWAITING_HUMAN
    assert paused.gate.gate_id == "insurance.claim_rejection"
    # the gate must say plainly that appealing is not an option here
    assert paused.gate.data["appealable"] is False
    assert paused.gate.data["resubmission_frequency_code"] == "7"
    assert paused.gate.data["rejections"][0]["status_code"] == "164"


async def test_rejected_claim_never_produces_a_remittance():
    """An 835 for a claim that never entered adjudication cannot happen. If the pipeline
    let one through it would reconcile the patient's balance against a fiction."""
    ctx = PipelineContext(encounter_id="R3", input_data=_in(claim_defect="npi"))
    ctx.add_decision(GateDecision(gate_id="insurance.claim_rejection", approved=True,
                                  actor="Biller Jo", note="NPI corrected from PMS"))
    done = await _orch().run(ctx)
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["claim_rejected"] is True
    assert done.output["remittance"] == {}            # skipped, not faked
    assert done.output["reconciliation"] == {}


async def test_worked_rejection_records_a_replacement_resubmission():
    ctx = PipelineContext(encounter_id="R4", input_data=_in(claim_defect="tooth"))
    ctx.add_decision(GateDecision(gate_id="insurance.claim_rejection", approved=True,
                                  actor="Biller Jo", note="tooth #19 added"))
    done = await _orch().run(ctx)
    handling = done.output["rejection_handling"]
    assert handling["action"] == "correct_and_resubmit"
    # frequency code 7 + the original control number, so the payer REPLACES rather than
    # treating it as a new claim (which would come back as CARC 18, duplicate)
    assert handling["frequency_code"] == "7"
    assert handling["resubmitted_as"] == "replacement"
    assert handling["original_control_number"]
    assert handling["elements_to_fix"]


async def test_biller_can_hold_a_rejected_claim():
    """Some rejections need the office to re-verify insurance with the patient first.
    Declining leaves the claim unpaid in AR rather than pretending it was fixed."""
    ctx = PipelineContext(encounter_id="R5", input_data=_in(claim_defect="member_id"))
    ctx.add_decision(GateDecision(gate_id="insurance.claim_rejection", approved=False,
                                  actor="Biller Jo", note="calling patient for card"))
    done = await _orch().run(ctx)
    assert done.status == PipelineStatus.PARTIAL       # not aborted, not completed
    assert done.errors
    assert done.output["remittance"] == {}
