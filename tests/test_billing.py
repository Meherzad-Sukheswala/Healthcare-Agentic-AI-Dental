"""
Billing across BOTH phases.

Phase 1 (Checkout): the patient authorizes and pays an ESTIMATE at the front desk,
before any claim exists. Coding QA gates high-cost encounters pre-submission.

Phase 2 (Reconciliation): the 835 ERA arrives 1-2 weeks later and the estimate is
settled — balance statement, refund, or nothing. Denials are only knowable here,
because a denial is a fact about the payer's response.
"""
from src.agents.billing import CheckoutOrchestrator, ReconciliationOrchestrator
from src.config import Settings
from src.core.llm import LLMClient
from src.core.orchestrator import GateDecision, PipelineContext
from src.integrations import build_registry
from src.shared.enums import PipelineStatus

COVERAGE = {"active": True, "copay_cents": 3000, "coinsurance_pct": 0.2, "deductible_remaining_cents": 25000}


def _checkout():
    s = Settings(_env_file=None)
    return CheckoutOrchestrator(registry=build_registry(s), llm_client=LLMClient(s))


def _recon():
    s = Settings(_env_file=None)
    return ReconciliationOrchestrator(registry=build_registry(s), llm_client=LLMClient(s))


def _in(charge):
    return {"patient_id": "PAT-001", "charge_cents": charge, "coverage": COVERAGE,
            "payment_token": "tok_visa", "cdt": "D0140", "icd10": "K04.7"}


def _auth():
    return GateDecision(gate_id="billing.payment_auth", approved=True, actor="Maria Garcia")


def _remit(patient_resp, billed=15000, allowed=12000, status="paid"):
    return {"billed_cents": billed, "allowed_cents": allowed,
            "paid_cents": max(0, allowed - patient_resp),
            "patient_responsibility_cents": patient_resp,
            "adjustments": [], "status": status}


# ------------------------------------------------------------------ phase 1
async def test_checkout_payment_auth_gate_then_charges_the_estimate():
    paused = await _checkout().run(PipelineContext(encounter_id="B1", input_data=_in(15000)))
    assert paused.gate.gate_id == "billing.payment_auth"

    ctx = PipelineContext(encounter_id="B1", input_data=_in(15000))
    ctx.add_decision(_auth())
    done = await _checkout().run(ctx)
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["amount_due_cents"] == 15000            # deductible absorbs it
    assert done.output["payment"]["status"] == "succeeded"
    # what reconciliation will settle against
    assert done.output["collected_cents"] == 15000
    assert done.output["estimated_patient_cents"] == 15000


async def test_checkout_high_cost_triggers_coding_qa_gate_first():
    paused = await _checkout().run(PipelineContext(encounter_id="B2", input_data=_in(250000)))
    assert paused.gate.gate_id == "billing.coding_qa"

    ctx = PipelineContext(encounter_id="B2", input_data=_in(250000))
    ctx.add_decision(GateDecision(gate_id="billing.coding_qa", approved=True, actor="CDI Specialist"))
    ctx.add_decision(_auth())
    done = await _checkout().run(ctx)
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["payment"]["status"] == "succeeded"
    assert done.output["amount_due_cents"] == 72400            # 3000 + 25000 + 20% of 222000


async def test_checkout_declined_payment_collects_nothing():
    """A declined card leaves the whole estimate outstanding for reconciliation."""
    data = _in(15000) | {"payment_token": ""}
    ctx = PipelineContext(encounter_id="B4", input_data=data)
    ctx.add_decision(_auth())
    done = await _checkout().run(ctx)
    assert done.output["payment"]["status"] == "declined"
    assert done.output["collected_cents"] == 0


# ------------------------------------------------------------------ phase 2
async def test_reconciliation_balanced_when_estimate_was_right():
    ctx = PipelineContext(encounter_id="R1", input_data={
        "patient_id": "PAT-001", "remittance": _remit(15000),
        "collected_cents": 15000, "estimated_patient_cents": 15000, "addons_cents": 0,
        "claim_status": "paid"})
    done = await _recon().run(ctx)
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["outcome"] == "balanced"
    assert done.output["balance_due_cents"] == 0
    assert done.output["refund_due_cents"] == 0
    assert done.output["estimate_variance_cents"] == 0


async def test_reconciliation_balance_due_when_payer_paid_less_than_estimated():
    ctx = PipelineContext(encounter_id="R2", input_data={
        "patient_id": "PAT-001", "remittance": _remit(20000),
        "collected_cents": 15000, "estimated_patient_cents": 15000, "addons_cents": 0,
        "claim_status": "paid"})
    done = await _recon().run(ctx)
    assert done.output["outcome"] == "balance_due"
    assert done.output["balance_due_cents"] == 5000
    assert done.output["refund_due_cents"] == 0
    assert done.output["estimate_variance_cents"] == 5000


async def test_reconciliation_refund_due_when_payer_paid_more_than_estimated():
    ctx = PipelineContext(encounter_id="R3", input_data={
        "patient_id": "PAT-001", "remittance": _remit(10000),
        "collected_cents": 15000, "estimated_patient_cents": 15000, "addons_cents": 0,
        "claim_status": "paid"})
    done = await _recon().run(ctx)
    assert done.output["outcome"] == "refund_due"
    assert done.output["refund_due_cents"] == 5000
    assert done.output["balance_due_cents"] == 0


async def test_reconciliation_addons_are_patient_oop_and_not_double_counted():
    """Retail items + tax were collected at checkout and are never insured, so they
    add to the payer-determined service share rather than being reconciled away."""
    ctx = PipelineContext(encounter_id="R4", input_data={
        "patient_id": "PAT-001", "remittance": _remit(15000),
        "collected_cents": 20000, "estimated_patient_cents": 20000, "addons_cents": 5000,
        "claim_status": "paid"})
    done = await _recon().run(ctx)
    assert done.output["actual_patient_cents"] == 20000       # 15000 service + 5000 addons
    assert done.output["outcome"] == "balanced"


async def test_reconciliation_self_pay_has_nothing_to_settle():
    ctx = PipelineContext(encounter_id="R5", input_data={
        "patient_id": "PAT-001", "remittance": {},
        "collected_cents": 15000, "estimated_patient_cents": 15000, "addons_cents": 0,
        "claim_status": "received"})
    done = await _recon().run(ctx)
    assert done.output["outcome"] == "not_applicable"
    assert done.output["statement"]["reason"] == "self_pay_no_remittance"


async def test_reconciliation_write_off_is_reported_separately():
    """The contractual write-off is the payer's discount, never billable to an
    in-network patient — so it must surface as its own number."""
    ctx = PipelineContext(encounter_id="R6", input_data={
        "patient_id": "PAT-001", "remittance": _remit(15000, billed=20000, allowed=16000),
        "collected_cents": 15000, "estimated_patient_cents": 15000, "addons_cents": 0,
        "claim_status": "paid"})
    done = await _recon().run(ctx)
    assert done.output["write_off_cents"] == 4000
    assert done.output["outcome"] == "balanced"


async def test_reconciliation_denied_claim_hits_appeal_gate():
    data = {"patient_id": "PAT-001", "remittance": _remit(0, allowed=0, status="denied"),
            "collected_cents": 15000, "estimated_patient_cents": 15000, "addons_cents": 0,
            "claim_status": "denied"}
    paused = await _recon().run(PipelineContext(encounter_id="R7", input_data=dict(data)))
    assert paused.gate.gate_id == "billing.denial"

    ctx = PipelineContext(encounter_id="R7", input_data=dict(data))
    ctx.add_decision(GateDecision(gate_id="billing.denial", approved=True, actor="Biller Jo", note="appeal"))
    done = await _recon().run(ctx)
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["denied"] is True
    assert done.output["appeal"]["appeal_filed"] is True
