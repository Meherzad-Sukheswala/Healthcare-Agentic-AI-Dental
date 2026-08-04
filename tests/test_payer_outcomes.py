"""
The DENIAL half of the claim cycle: the payer adjudicated and did not pay as billed.

Eight reasons route to five actions and only two are appeals. These tests exist to stop
that collapsing back into one "denied -> appeal" bucket, because the routing is the part
that has real money attached:

  * a missing attachment is a RESUBMISSION, not an appeal
  * a frequency cap or exhausted annual maximum is the PATIENT'S bill, not an appeal
  * a timely-filing denial is a write-off — appealing it cannot succeed
  * a LEAT downgrade is a PAID claim whose differential the patient owes
"""
from src.agents.billing import ReconciliationOrchestrator
from src.config import Settings
from src.core.llm import LLMClient
from src.core.orchestrator import GateDecision, PipelineContext
from src.integrations import build_registry
from src.shared.enums import PipelineStatus
from src.shared.payer_outcomes import (
    ACTION_APPEAL,
    ACTION_BILL_PATIENT,
    ACTION_REBILL_OTHER_PAYER,
    ACTION_RESUBMIT_ATTACHMENT,
    ACTION_WRITE_OFF,
    alternate_allowed_cents,
    classify,
)

COVERED = {"service_covered": True, "annual_max_cents": 150000, "annual_max_used_cents": 0,
           "timely_filing_days": 365}


def _claim(*codes):
    return {"service_lines": [{"cdt": c, "tooth": "19", "charge_cents": 100000} for c in codes]}


def _orch():
    s = Settings(_env_file=None)
    return ReconciliationOrchestrator(registry=build_registry(s), llm_client=LLMClient(s))


# --------------------------------------------------------------- classification
def test_clean_claim_is_paid_with_no_action():
    out = classify(_claim("D3330"), COVERED, {})
    assert out.status == "paid"
    assert out.action == "none"


def test_unanswered_documentation_request_becomes_a_resubmission_not_an_appeal():
    """A payer's FIRST move on a claim it can't judge is to pend (277RFAI). This denial is
    what happens when that request goes unanswered — and appealing it wastes the 30-90 day
    cycle on a same-day fix, which is the costliest routing mistake in the set."""
    out = classify(_claim("D2740"), COVERED, {"documentation_complete": False})
    assert out.status == "denied"
    assert out.reason == "missing_attachment"
    assert out.action == ACTION_RESUBMIT_ATTACHMENT
    assert out.appealable is False
    assert out.carc == "16" and out.rarc == "N706"


def test_attachment_not_required_for_routine_codes():
    """A prophy claim with no radiograph attached is not a denial — preventive codes are
    paid on frequency, not justification, so they are never pended for records either."""
    assert classify(_claim("D1110"), COVERED, {"documentation_complete": False}).status == "paid"


def test_frequency_limitation_bills_the_patient_and_is_not_appealable():
    out = classify(_claim("D1110"), COVERED, {"prior_procedures": ["D1110", "D1110"]})
    assert out.reason == "frequency_limitation"
    assert out.action == ACTION_BILL_PATIENT
    assert out.appealable is False
    assert out.carc == "119"


def test_one_prior_cleaning_does_not_exhaust_a_two_per_year_benefit():
    assert classify(_claim("D1110"), COVERED, {"prior_procedures": ["D1110"]}).status == "paid"


def test_exhausted_annual_maximum_bills_the_patient():
    exhausted = {**COVERED, "annual_max_used_cents": 150000}
    out = classify(_claim("D3330"), exhausted, {})
    assert out.reason == "annual_maximum"
    assert out.action == ACTION_BILL_PATIENT
    assert out.appealable is False


def test_timely_filing_is_a_write_off():
    out = classify(_claim("D3330"), COVERED, {"days_since_service": 400})
    assert out.reason == "timely_filing"
    assert out.action == ACTION_WRITE_OFF
    assert out.appealable is False
    assert out.carc == "29"


def test_timely_filing_respects_the_payers_own_limit():
    """Limits run from 90 days to 12 months; 200 days is late for Medicaid at 180 and
    fine for a commercial plan at 365."""
    assert classify(_claim("D3330"), {**COVERED, "timely_filing_days": 180},
                    {"days_since_service": 200}).reason == "timely_filing"
    assert classify(_claim("D3330"), COVERED, {"days_since_service": 200}).status == "paid"


def test_not_covered_is_the_one_that_actually_warrants_an_appeal():
    out = classify(_claim("D3330"), {**COVERED, "service_covered": False}, {})
    assert out.reason == "not_covered"
    assert out.action == ACTION_APPEAL
    assert out.appealable is True
    assert out.carc == "96"


def test_other_coverage_primary_rebills_rather_than_appeals():
    out = classify(_claim("D3330"), COVERED, {"other_coverage_primary": True})
    assert out.action == ACTION_REBILL_OTHER_PAYER
    assert out.carc == "22"


def test_duplicate_needs_no_action():
    out = classify(_claim("D3330"), COVERED, {"duplicate": True})
    assert out.reason == "duplicate"
    assert out.action == "none"
    assert out.carc == "18"


def test_administrative_gates_are_checked_before_benefit_logic():
    """A claim that is both late AND over the annual max is a timely-filing denial — a
    payer never gets to the benefit math on a claim it won't accept."""
    exhausted = {**COVERED, "annual_max_used_cents": 150000}
    assert classify(_claim("D3330"), exhausted, {"days_since_service": 400}).reason == "timely_filing"


# ------------------------------------------------------- alternate benefit (LEAT)
def test_leat_only_applies_to_plans_that_carry_the_provision():
    assert classify(_claim("D2740"), COVERED, {}).status == "paid"
    leat = {**COVERED, "alternate_benefit_provision": True}
    assert classify(_claim("D2740"), leat, {}).status == "paid_alternate_benefit"


def test_leat_is_a_paid_claim_whose_differential_the_patient_owes():
    leat = {**COVERED, "alternate_benefit_provision": True}
    out = classify(_claim("D2740"), leat, {})
    assert out.status == "paid_alternate_benefit"      # NOT denied
    assert out.action == ACTION_BILL_PATIENT
    assert out.appealable is True                       # arguable with a narrative
    assert "alternate benefit" in out.carc_description.lower()


def test_alternate_allowed_uses_the_cheaper_fee_only_on_downgradable_lines():
    lines = [{"cdt": "D2740", "charge_cents": 175000},    # porcelain crown -> cast metal
             {"cdt": "D3330", "charge_cents": 145000}]    # endo has no alternative
    assert alternate_allowed_cents(lines) == 105000 + 145000


def test_alternate_allowed_never_exceeds_what_was_billed():
    """A plan never allows more than the charge — a practice billing below the metal-crown
    rate must not be paid up to it."""
    assert alternate_allowed_cents([{"cdt": "D2740", "charge_cents": 90000}]) == 90000


# ------------------------------------------------- routing through the pipeline
def _remit(status, **over):
    r = {"billed_cents": 145000, "allowed_cents": 0, "paid_cents": 0,
         "patient_responsibility_cents": 0, "status": status, "adjustments": []}
    r.update(over)
    return r


async def test_resubmit_denial_opens_the_gate_worded_as_a_resubmission():
    data = {"patient_id": "PAT-001", "collected_cents": 30000, "estimated_patient_cents": 30000,
            "remittance": _remit("denied", reason="missing_attachment",
                                 action=ACTION_RESUBMIT_ATTACHMENT, appealable=False,
                                 explanation="Payer wants the periapical radiograph."),
            "attachments_recommended": ["preoperative periapical radiograph"]}
    paused = await _orch().run(PipelineContext(encounter_id="P1", input_data=data))
    assert paused.gate.gate_id == "billing.denial"
    assert "resubmit, do not appeal" in paused.gate.title
    assert paused.gate.data["recommended_action"] == ACTION_RESUBMIT_ATTACHMENT

    ctx = PipelineContext(encounter_id="P1", input_data=data)
    ctx.add_decision(GateDecision(gate_id="billing.denial", approved=True, actor="Biller Jo"))
    done = await _orch().run(ctx)
    assert done.output["appeal"]["resubmitted_with_attachment"] is True
    assert done.output["appeal"]["appeal_filed"] is False
    assert done.output["appeal"]["frequency_code"] == "7"


async def test_pending_appeal_does_not_refund_the_patient():
    """The payer said it will pay nothing YET. Reading that as "patient owes nothing, so
    refund the estimate" hands back money the resubmitted claim may still collect — the
    account is unresolved, not settled."""
    data = {"patient_id": "PAT-001", "collected_cents": 68400, "estimated_patient_cents": 68400,
            "remittance": _remit("denied", reason="missing_attachment",
                                 action=ACTION_RESUBMIT_ATTACHMENT, appealable=False)}
    ctx = PipelineContext(encounter_id="P1b", input_data=data)
    ctx.add_decision(GateDecision(gate_id="billing.denial", approved=True, actor="Biller Jo"))
    done = await _orch().run(ctx)
    assert done.output["outcome"] == "unresolved"
    assert done.output["refund_due_cents"] == 0
    assert done.output["balance_due_cents"] == 0
    assert done.output["statement"]["pending_action"] == ACTION_RESUBMIT_ATTACHMENT


async def test_write_off_leaves_the_patients_own_cost_share_standing():
    """Untimely filing is the practice's failure and cannot be balance-billed — but the
    patient's normal copay/deductible/coinsurance is still theirs. Refunding it would be
    the practice paying twice for its own late filing."""
    data = {"patient_id": "PAT-001", "collected_cents": 30000, "estimated_patient_cents": 30000,
            "remittance": _remit("denied", reason="timely_filing", action=ACTION_WRITE_OFF,
                                 appealable=False, patient_responsibility_cents=30000)}
    done = await _orch().run(PipelineContext(encounter_id="P1c", input_data=data))
    assert done.output["outcome"] == "balanced"
    assert done.output["refund_due_cents"] == 0


async def test_frequency_denial_does_not_open_the_appeal_gate_at_all():
    """The patient owes this. Putting it in a biller's appeal queue is pure waste."""
    data = {"patient_id": "PAT-001", "collected_cents": 0, "estimated_patient_cents": 0,
            "remittance": _remit("denied", reason="frequency_limitation",
                                 action=ACTION_BILL_PATIENT, appealable=False,
                                 patient_responsibility_cents=145000)}
    done = await _orch().run(PipelineContext(encounter_id="P2", input_data=data))
    assert done.status == PipelineStatus.COMPLETED       # no pause
    assert done.output["denied"] is True
    assert done.output["recommended_action"] == ACTION_BILL_PATIENT
    assert done.output["appeal"] == {}                   # gate never ran
    # and the money lands on the patient's statement
    assert done.output["balance_due_cents"] == 145000


async def test_leat_downgrade_reports_as_downgraded_not_denied():
    data = {"patient_id": "PAT-001", "collected_cents": 30000, "estimated_patient_cents": 30000,
            "remittance": _remit("paid_alternate_benefit", reason="alternate_benefit",
                                 action=ACTION_BILL_PATIENT, appealable=True,
                                 allowed_cents=105000, paid_cents=45000,
                                 patient_responsibility_cents=100000)}
    done = await _orch().run(PipelineContext(encounter_id="P3", input_data=data))
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["denied"] is False                # paid, not denied
    assert done.output["downgraded"] is True
    assert done.output["outcome"] == "balance_due"       # patient owes the differential


async def test_unexplained_denial_still_reaches_a_human():
    """A denial with no stated reason must fail toward the appeal gate — an unexplained
    denial nobody looks at is worse than one wrongly queued."""
    data = {"patient_id": "PAT-001", "collected_cents": 0, "estimated_patient_cents": 0,
            "remittance": _remit("denied")}
    paused = await _orch().run(PipelineContext(encounter_id="P4", input_data=data))
    assert paused.gate.gate_id == "billing.denial"
    assert paused.gate.data["denial_reason"] == "unspecified"


async def test_rejected_claim_is_not_reported_as_a_denial():
    """A rejection was handled upstream at insurance.claim_rejection. Surfacing it here
    as a denial would double-count it and offer a biller an appeal that cannot be filed."""
    data = {"patient_id": "PAT-001", "collected_cents": 30000,
            "estimated_patient_cents": 30000, "remittance": {}, "claim_rejected": True}
    done = await _orch().run(PipelineContext(encounter_id="P5", input_data=data))
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["denied"] is False
    assert done.output["denial"]["claim_status"] == "rejected"
    # the balance is unresolved in AR, not settled
    assert done.output["outcome"] == "unresolved"
    assert done.output["statement"]["awaiting_corrected_claim"] is True
