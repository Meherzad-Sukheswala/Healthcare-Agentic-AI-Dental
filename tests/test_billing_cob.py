"""
Checkout coordination-of-benefits: uninsured, commercial, Medicare, Medicaid,
dual-eligible, and commercial+secondary. Verifies the exact ESTIMATED patient
responsibility for each payer scenario -- this runs at checkout, before any claim, so
there is no remittance and BillSplitter is in estimate mode. All resume past the
payment-auth gate.
"""
from src.agents.billing import CheckoutOrchestrator
from src.config import Settings
from src.core.llm import LLMClient
from src.core.orchestrator import GateDecision, PipelineContext
from src.integrations import build_registry
from src.shared.enums import PipelineStatus

CHARGE = 100000   # $1,000.00 charge used across scenarios

COMMERCIAL = {"payer_type": "commercial", "active": True, "copay_cents": 3000,
              "coinsurance_pct": 0.2, "deductible_remaining_cents": 0}
MEDICARE = {"payer_type": "medicare", "active": True, "copay_cents": 0,
            "coinsurance_pct": 0.2, "deductible_remaining_cents": 24000}
MEDICAID = {"payer_type": "medicaid", "active": True, "copay_cents": 400,
            "coinsurance_pct": 0.0, "deductible_remaining_cents": 0}
SECONDARY = {"payer_type": "commercial", "active": True, "copay_cents": 0,
             "coinsurance_pct": 0.1, "deductible_remaining_cents": 0}


def _orch():
    s = Settings(_env_file=None)
    return CheckoutOrchestrator(registry=build_registry(s), llm_client=LLMClient(s))


async def _run(payers, charge=CHARGE, discount=None):
    data = {"patient_id": "PAT-001", "charge_cents": charge, "payers": payers,
            "payment_token": "tok_visa", "claim_status": "received"}
    if discount is not None:
        data["self_pay_discount_pct"] = discount
    ctx = PipelineContext(encounter_id="COB", input_data=dict(data))
    ctx.add_decision(GateDecision(gate_id="billing.coding_qa", approved=True, actor="CDI"))
    ctx.add_decision(GateDecision(gate_id="billing.payment_auth", approved=True, actor="Patient"))
    return await _orch().run(ctx)


async def test_uninsured_owes_full_charge():
    res = await _run([])
    assert res.status == PipelineStatus.COMPLETED
    assert res.output["amount_due_cents"] == CHARGE


async def test_self_pay_discount_applied():
    res = await _run([], discount=0.20)
    assert res.output["amount_due_cents"] == 80000        # 20% prompt-pay discount


async def test_commercial_copay_coinsurance():
    # copay 3000 + 20% of (100000-3000) = 3000 + 19400 = 22400
    res = await _run([COMMERCIAL])
    assert res.output["amount_due_cents"] == 22400


async def test_medicare_part_b():
    # deductible 24000 + 20% of (100000-24000)=15200 -> 39200
    res = await _run([MEDICARE])
    assert res.output["amount_due_cents"] == 39200


async def test_medicaid_last_resort_near_zero():
    res = await _run([MEDICAID])
    assert res.output["amount_due_cents"] == 400          # nominal copay only


async def test_dual_eligible_medicare_then_medicaid():
    # Medicare leaves 39200 patient resp; Medicaid (last resort) absorbs it -> nominal 400
    res = await _run([MEDICARE, MEDICAID])
    assert res.output["amount_due_cents"] == 400


async def test_commercial_with_secondary_cob():
    # primary leaves 22400; secondary pays 90%, patient owes 10% -> 2240
    res = await _run([COMMERCIAL, SECONDARY])
    assert res.output["amount_due_cents"] == 2240


async def test_provider_configured_self_pay_discount(monkeypatch):
    # No per-encounter discount; provider policy (env) applies a 15% self-pay discount.
    import src.config as cfg
    monkeypatch.setenv("SELF_PAY_DISCOUNT_PCT", "0.15")
    cfg.get_settings.cache_clear()
    try:
        res = await _run([])                     # uninsured, no per-encounter override
        assert res.output["amount_due_cents"] == 85000     # 15% off $1,000
    finally:
        cfg.get_settings.cache_clear()           # reset the cached singleton

