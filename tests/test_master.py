"""
End-to-end encounter through the MasterOrchestrator: it runs all domains in order,
hands data between them, and pauses at each human gate. This test drives a full
encounter to completion by resolving whatever gate is returned, then checks aborts
and the first pause point.
"""
from src.config import Settings
from src.core.llm import LLMClient
from src.core.pipeline import MasterOrchestrator
from src.integrations import build_registry

# canned approvals for any gate the encounter can raise
APPROVALS = {
    "scheduling.slot_selection": {"approved": True, "actor": "Patient", "note": "0"},
    "scheduling.referral": {"approved": True, "actor": "PCP"},
    "patient.mpi": {"approved": True, "actor": "MPI Steward"},
    "patient.consent": {"approved": True, "actor": "Patient"},
    "clinical.critical_value": {"approved": True, "actor": "RN"},
    "clinical.diagnosis": {"approved": True, "actor": "Dr. Rao, MD"},
    "clinical.treatment_plan": {"approved": True, "actor": "Dr. Rao, MD"},
    "clinical.treatment_consent": {"approved": True, "actor": "Maria Garcia"},
    "clinical.epcs": {"approved": True, "actor": "Dr. Rao, MD", "note": "654321"},
    "insurance.predetermination": {"approved": True, "actor": "Payer MD"},
    "billing.coding_qa": {"approved": True, "actor": "CDI"},
    "billing.payment_auth": {"approved": True, "actor": "Patient"},
    "billing.denial": {"approved": True, "actor": "Biller"},
    "pharmacy.verification": {"approved": True, "actor": "PharmD Lee"},
}


def _master():
    s = Settings(_env_file=None)
    return MasterOrchestrator(build_registry(s), LLMClient(s))


def _request(**over):
    req = {
        "patient_id": "PAT-001",
        "chief_complaint": "tooth pain and swelling",
        "prescribe": [{"rx_id": "RX-1", "rxcui": "161", "display": "acetaminophen",
                       "ndc": "0069-2587-10", "schedule": "non_controlled"}],
        "payment_token": "tok_visa", "state": "CA", "decisions": {},
    }
    req.update(over)
    return req


async def test_full_encounter_completes_through_all_gates():
    master = _master()
    request = _request()
    seen = []
    for _ in range(15):                      # safety bound
        res = await master.execute_encounter(request)
        if res.status == "awaiting_human":
            gate = res.awaiting_gate.gate_id
            seen.append(gate)
            request["decisions"][gate] = APPROVALS[gate]
            continue
        break

    assert res.status == "completed"
    # a real treatment plan (root canal + crown) now pushes the charge over the
    # coding-QA threshold, so that gate joins the standard stop sequence
    assert seen == ["scheduling.slot_selection", "patient.consent", "clinical.diagnosis",
                    "clinical.treatment_plan", "clinical.treatment_consent",
                    "billing.coding_qa", "billing.payment_auth", "pharmacy.verification"]
    s = res.summary
    assert s["diagnosis_icd10"] == "K04.7"
    assert s["cdt"] == "D3330"
    assert s["claim_accepted"] is True
    assert s["eligibility_verified"] is True        # verified pre-visit, in scheduling

    # ---- the two-phase bill, which is the whole point of the domain ordering ----
    # PHASE 1, at checkout: the patient pays an ESTIMATE built from the pre-visit
    # benefit check, against the FULL $2,300 fee. No claim exists yet, so no
    # contractual write-off is known:
    #   copay 3000 + deductible 25000 + 20% of (230000-3000-25000) = 68400
    assert s["amount_due_cents"] == 68400
    assert s["collected_cents"] == 68400
    assert s["payment_status"] == "succeeded"

    # PHASE 2, ~2 weeks later, once the 835 ERA lands: the payer's allowed amount is
    # $1,840 (a 20% in-network write-off on $2,300), so the patient's TRUE share is
    #   copay 3000 + deductible 25000 + 20% of (184000-3000-25000) = 59200
    assert s["write_off_cents"] == 46000
    assert s["actual_patient_cents"] == 59200

    # The estimate was $92 too high, so the practice owes a refund — not a bill.
    # This is the outcome the old Insurance-before-Billing order could not produce.
    assert s["reconciliation_outcome"] == "refund_due"
    assert s["refund_due_cents"] == 9200
    assert s["balance_due_cents"] == 0
    assert s["estimate_variance_cents"] == -9200

    assert s["dispensed"] is True
    # root canal (D3) -> short post-endodontic follow-up, not a routine 6-month recall
    assert s["recall_interval_months"] == 1
    assert s["recall_due_date"]
    assert s["fraud_alert"] is False


async def test_first_pause_is_slot_selection():
    res = await _master().execute_encounter(_request())
    assert res.status == "awaiting_human"
    assert res.awaiting_domain == "scheduling"
    assert res.awaiting_gate.gate_id == "scheduling.slot_selection"


async def test_unknown_patient_aborts_encounter():
    # let scheduling complete (pick a slot), then Patient demographics fails -> abort
    res = await _master().execute_encounter(_request(patient_id="PAT-999", decisions={
        "scheduling.slot_selection": APPROVALS["scheduling.slot_selection"],
        "patient.consent": APPROVALS["patient.consent"],
    }))
    assert res.status == "failed"
    assert res.awaiting_domain == ""            # failed, not paused
