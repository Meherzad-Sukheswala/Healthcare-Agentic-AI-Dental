"""Insurance domain: clean claim, predetermination review gate, remittance/reconciliation, denial-as-partial."""
from src.agents.insurance import InsuranceOrchestrator
from src.config import Settings
from src.core.llm import LLMClient
from src.core.orchestrator import GateDecision, PipelineContext
from src.integrations import build_registry
from src.integrations.seed_data import PROVIDERS
from src.shared.enums import PipelineStatus


def _orch():
    s = Settings(_env_file=None)
    return InsuranceOrchestrator(registry=build_registry(s), llm_client=LLMClient(s))


# Documentation this encounter holds. Substantive procedures get PENDED for records, so a
# fixture without a registry would escalate to the document gate on every claim — which is
# correct behaviour, just not what these tests are about. See test_information_request.py
# for the pend/escalation paths themselves.
ON_FILE = {
    "preop_radiograph": {"available": True, "count": 1, "detail": "PA #19 pre-op"},
    "postop_radiograph": {"available": True, "count": 1, "detail": "PA #19 post-op"},
    "bitewings": {"available": True, "count": 1, "detail": "BW x4"},
    "full_mouth_series": {"available": True, "count": 1, "detail": "FMX, 18 films"},
    "cbct": {"available": True, "count": 1, "detail": "CBCT mandible, site #19"},
    "perio_charting": {"available": True, "count": 1, "detail": "probing depths recorded"},
    "chart_note": {"available": True, "count": 1, "detail": "signed note"},
    "narrative": {"available": True, "count": 1, "detail": "1 narrative"},
}


def _in(cdt, **over):
    # A tooth number is supplied because implant/crown/endo codes are REJECTED by the
    # payer's relational edits without one; D0140 (exam) doesn't need it but carrying it
    # keeps one fixture usable for both.
    data = {
        "member_id": "BCB-90001", "payer_id": "PAYER-001", "cdt": cdt, "icd10": "K04.7",
        "tooth": "19", "provider_npi": PROVIDERS[0].npi, "ndcs": ["0069-2587-10"],
        "document_registry": dict(ON_FILE),
    }
    data.update(over)
    return data


async def test_clean_claim_gets_remittance_back():
    res = await _orch().run(PipelineContext(encounter_id="I1", input_data=_in("D0140")))
    assert res.status == PipelineStatus.COMPLETED
    assert res.output["coverage"]["active"] is True
    assert res.output["claim_ack"]["accepted"] is True
    # the payer's response to the claim — not just a synchronous "accepted" flag
    remit = res.output["remittance"]
    assert remit["billed_cents"] == 9500
    assert remit["allowed_cents"] < remit["billed_cents"]        # commercial network write-off applied
    assert remit["paid_cents"] + remit["patient_responsibility_cents"] == remit["allowed_cents"]
    assert res.output["reconciliation"]["needs_follow_up"] is False


async def test_predetermination_review_gate():
    paused = await _orch().run(PipelineContext(encounter_id="I2", input_data=_in("D6010")))
    assert paused.status == PipelineStatus.AWAITING_HUMAN
    assert paused.gate.gate_id == "insurance.predetermination"

    ctx = PipelineContext(encounter_id="I2", input_data=_in("D6010"))
    ctx.add_decision(GateDecision(gate_id="insurance.predetermination", approved=True, actor="Dr. Payer"))
    done = await _orch().run(ctx)
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["claim_ack"]["accepted"] is True
    assert done.output["remittance"]["billed_cents"] == 240000


async def test_denial_is_partial_not_abort():
    ctx = PipelineContext(encounter_id="I3", input_data=_in("D6010"))
    ctx.add_decision(GateDecision(gate_id="insurance.predetermination", approved=False, actor="Dr. Payer", note="not necessary"))
    res = await _orch().run(ctx)
    assert res.status == PipelineStatus.PARTIAL          # denial does not abort
    assert res.output["claim_ack"]["accepted"] is True   # downstream still ran
    assert res.errors
