"""
The "payer wants more evidence" round trip: 837D -> 277CA accepted -> 277RFAI pend ->
275 attachment -> 835 ERA.

The behaviour worth protecting is the routing. A payer asking for three documents where
two are already on file should cost the practice ONE small task, not three — and when
nothing is missing it should cost zero. That only holds if "is it already in the record"
is answered from real artifacts, which is what the document registry is for.
"""
from src.agents.insurance import InsuranceOrchestrator
from src.config import Settings
from src.core.llm import LLMClient
from src.core.orchestrator import GateDecision, PipelineContext
from src.integrations import build_registry as build_service_registry
from src.integrations.seed_data import PROVIDERS
from src.shared.document_registry import BY_ADMIN, BY_DENTIST, BY_HYGIENIST, build_registry, resolve
from src.shared.enums import PipelineStatus
from src.shared.payer_outcomes import documentation_expected_for

NPI = PROVIDERS[0].npi


def _orch():
    s = Settings(_env_file=None)
    return InsuranceOrchestrator(registry=build_service_registry(s), llm_client=LLMClient(s))


def _performed(cdt="D3330", tooth="19", fee=145000):
    return [{"item_id": "TX1", "cdt": cdt, "tooth": tooth, "fee_cents": fee,
             "description": "Endodontic therapy", "phase": "phase1", "status": "completed"}]


def _in(registry=None, **over):
    data = {"member_id": "BCB-90001", "payer_id": "PAYER-001", "cdt": "D3330",
            "icd10": "K04.7", "tooth": "19", "provider_npi": NPI,
            "performed_items": _performed(), "diagnosis_codes": ["K04.7"],
            "line_diagnoses": [{"item_id": "TX1", "cdt": "D3330", "tooth": "19",
                                "icd10": "K04.7", "diagnosis_pointer": "A"}],
            "document_registry": registry if registry is not None else {},
            "ndcs": []}
    data.update(over)
    return data


BOTH_FILMS = {
    "preop_radiograph": {"available": True, "count": 1, "detail": "PA #19 pre-op"},
    "postop_radiograph": {"available": True, "count": 1, "detail": "PA #19 post-op"},
}


# ------------------------------------------------------------------ the registry
def test_registry_reports_only_what_was_actually_captured():
    reg = build_registry(
        imaging={"images": {"preop_radiograph": ["PA #30 pre-op"]}},
        clinical_note="S: pt reports pain. A: K04.7", narratives=[{"cdt": "D3330"}],
        treatment_plan_items=[{"item_id": "TX1"}], perio_charted=False)
    assert reg["preop_radiograph"]["available"] is True
    assert reg["chart_note"]["available"] is True
    assert reg["narrative"]["available"] is True
    # never captured, so it must NOT appear as available
    assert "postop_radiograph" not in reg
    assert "perio_charting" not in reg


def test_resolve_sends_existing_documents_to_the_ai():
    out = resolve("preop_radiograph", BOTH_FILMS)
    assert out["available"] is True
    assert out["resolved_by"] == "ai"
    assert out["needs_patient_visit"] is False


def test_resolve_names_the_human_and_flags_a_patient_recall():
    """A film that was never taken means the patient comes back. A referral form does
    not — it means waiting on another office. Both are human work; only one is a recall."""
    film = resolve("preop_radiograph", {})
    assert film["resolved_by"] == BY_DENTIST
    assert film["needs_patient_visit"] is True

    perio = resolve("perio_charting", {})
    assert perio["resolved_by"] == BY_HYGIENIST
    assert perio["needs_patient_visit"] is True

    referral = resolve("specialist_referral", {})
    assert referral["resolved_by"] == BY_ADMIN
    assert referral["needs_patient_visit"] is False


def test_documentation_expected_is_deduplicated_across_lines():
    """A payer asks for one full-mouth series, not one per quadrant."""
    keys = [d["doc_key"] for d in documentation_expected_for(["D4341", "D4341"])]
    assert keys.count("full_mouth_series") == 1


def test_routine_codes_are_never_pended_for_records():
    assert documentation_expected_for(["D1110", "D0120", "D0140"]) == []


# ------------------------------------------------- the fully automated round trip
async def test_payer_pends_and_the_ai_answers_with_no_human_involved():
    """The headline case: both films exist, so the request is satisfied and adjudicated
    without a single person being interrupted."""
    done = await _orch().run(PipelineContext(encounter_id="Q1", input_data=_in(BOTH_FILMS)))
    assert done.status == PipelineStatus.COMPLETED

    assert done.output["pended"] is True
    assert done.output["document_response_fully_automated"] is True
    assert done.output["documents_escalated"] == []
    assert done.output["documents_supplied_by_staff"] == {}      # gate never ran
    # the 275 went out with an attachment control number, and adjudication finished
    assert done.output["attachment_control_number"].startswith("NEA")
    assert done.output["attachment"]["complete"] is True
    assert done.output["remittance"]["status"] == "paid"
    assert done.output["claim_stage"] == "paid_after_documents"


async def test_pwk_segments_are_emitted_only_for_documents_actually_sent():
    """A PWK declaring an attachment that never arrives strands the claim at some payers —
    worse than sending nothing. So every PWK must have a payload behind it."""
    done = await _orch().run(PipelineContext(encounter_id="Q2", input_data=_in(BOTH_FILMS)))
    attachment = done.output["attachment"]
    assert len(attachment["pwk_segments"]) == len(attachment["documents"]) == 2
    acn = done.output["attachment_control_number"]
    for seg in attachment["pwk_segments"]:
        assert seg["PWK01"] == "RB"          # radiology films
        assert seg["PWK06"] == acn           # ties the 275 to the claim
    assert attachment["outstanding"] == []


async def test_proactive_attachment_skips_the_pend_entirely():
    """Sending records with the claim is best practice and there is then nothing to ask
    for — the payer must not pend a claim that already carries its documentation."""
    done = await _orch().run(PipelineContext(
        encounter_id="Q3", input_data=_in(BOTH_FILMS, attachments_ride_along=True)))
    assert done.output["pended"] is False
    assert done.output["documents_requested"] == []
    assert done.output["remittance"]["status"] == "paid"
    assert done.output["claim_stage"] == "paid"


# ------------------------------------------------------- the escalation round trip
async def test_missing_film_escalates_to_the_dentist_and_recalls_the_patient():
    only_preop = {"preop_radiograph": BOTH_FILMS["preop_radiograph"]}
    paused = await _orch().run(PipelineContext(encounter_id="Q4", input_data=_in(only_preop)))
    assert paused.status == PipelineStatus.AWAITING_HUMAN
    assert paused.gate.gate_id == "insurance.document_request"

    d = paused.gate.data
    # the AI already handled the one it could, and says so
    assert d["already_attached_count"] == 1
    assert [n["label"] for n in d["needed"]] == ["Postoperative periapical radiograph"]
    assert d["needed"][0]["produced_by"] == BY_DENTIST
    assert d["patient_must_return"] is True
    assert d["days_to_respond"] == 30


async def test_supplied_documents_are_merged_into_one_transmission():
    """What the AI found and what a person produced go out as a single 275, not two."""
    only_preop = {"preop_radiograph": BOTH_FILMS["preop_radiograph"]}
    ctx = PipelineContext(encounter_id="Q5", input_data=_in(only_preop))
    ctx.add_decision(GateDecision(gate_id="insurance.document_request", approved=True,
                                  actor="Dr. A. Rao, DDS", note="post-op PA taken at recall"))
    done = await _orch().run(ctx)
    assert done.status == PipelineStatus.COMPLETED

    attachment = done.output["attachment"]
    assert attachment["complete"] is True
    assert len(attachment["documents"]) == 2
    by = {d["label"]: d["obtained_by"] for d in attachment["documents"]}
    assert by["Preoperative periapical radiograph"] == "ai"
    assert by["Postoperative periapical radiograph"] == BY_DENTIST
    assert done.output["remittance"]["status"] == "paid"


async def test_ignoring_the_request_converts_the_pend_into_a_denial():
    """Sometimes answering isn't worth it — recalling a patient for a film can cost more
    than the claim. But the claim does not just sit there: the 30-day clock runs out and
    the payer converts the pend into a denial for missing information. Nothing is
    silently promised, and the outstanding document is named."""
    ctx = PipelineContext(encounter_id="Q6", input_data=_in({}))
    ctx.add_decision(GateDecision(gate_id="insurance.document_request", approved=False,
                                  actor="Biller Jo", note="not worth recalling the patient"))
    done = await _orch().run(ctx)
    assert done.status == PipelineStatus.PARTIAL
    assert done.errors

    # nothing was sent, and the assembler said so rather than emitting an empty PWK
    attachment = done.output["attachment"]
    assert attachment["documents"] == []
    assert attachment["complete"] is False
    assert attachment["pwk_segments"] == []
    assert attachment["outstanding"]

    remit = done.output["remittance"]
    assert remit["status"] == "denied"
    assert remit["reason"] == "missing_attachment"
    assert remit["action"] == "resubmit_with_attachment"     # still not an appeal
    assert done.output["claim_stage"] == "denied"


# --------------------------------------------------------------- the exchange view
async def test_exchange_records_the_whole_conversation_in_order():
    done = await _orch().run(PipelineContext(encounter_id="Q7", input_data=_in(BOTH_FILMS)))
    ex = done.output["exchange"]
    txns = [r["transaction"] for r in ex if r["transaction"]]
    assert txns == ["837D", "277CA", "277RFAI", "275", "835"]
    assert [r["seq"] for r in ex] == list(range(1, len(ex) + 1))


async def test_payer_side_rows_are_flagged_as_reconstructed():
    """A practice cannot see inside adjudication. Every payer-internal row must carry the
    flag that says so, or the UI would present inference as disclosed fact."""
    done = await _orch().run(PipelineContext(encounter_id="Q8", input_data=_in(BOTH_FILMS)))
    ex = done.output["exchange"]
    internal = [r for r in ex if r["actor"] == "payer" and r["direction"] == "internal"]
    assert internal, "expected reconstructed payer-side steps"
    assert all(r["simulated_internal"] for r in internal)
    # anything the practice genuinely receives is NOT flagged as reconstructed
    real = [r for r in ex if r["direction"] in ("in", "out")]
    assert all(not r["simulated_internal"] for r in real)


async def test_rejected_claim_exchange_stops_at_the_277ca():
    done_ctx = PipelineContext(encounter_id="Q9", input_data=_in(BOTH_FILMS, claim_defect="npi"))
    done_ctx.add_decision(GateDecision(gate_id="insurance.claim_rejection", approved=True,
                                       actor="Biller Jo", note="NPI corrected"))
    done = await _orch().run(done_ctx)
    txns = [r["transaction"] for r in done.output["exchange"] if r["transaction"]]
    assert "277RFAI" not in txns and "835" not in txns   # never adjudicated
    assert done.output["claim_stage"] == "rejected"
