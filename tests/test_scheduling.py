"""Scheduling: illness -> doctor match -> patient picks a slot -> booked; referral gate; abort."""
from src.agents.scheduling import SchedulerOrchestrator
from src.config import Settings
from src.core.llm import LLMClient
from src.core.orchestrator import GateDecision, PipelineContext
from src.integrations import build_registry
from src.shared.enums import PipelineStatus
from src.shared.medical_codes import is_valid_npi


def _orch():
    s = Settings(_env_file=None)
    return SchedulerOrchestrator(registry=build_registry(s), llm_client=LLMClient(s))


def _pick(note="0"):
    return GateDecision(gate_id="scheduling.slot_selection", approved=True, actor="Patient", note=note)


async def test_illness_to_doctor_to_patient_slot_pick():
    ctx = PipelineContext(encounter_id="E1", input_data={
        "patient_id": "PAT-001",
        "request_text": "I have palpitations and need a heart doctor",
    })
    paused = await _orch().run(ctx)
    # patient is shown open slots across matched cardiologists and must pick
    assert paused.status == PipelineStatus.AWAITING_HUMAN
    assert paused.gate.gate_id == "scheduling.slot_selection"
    opts = paused.gate.data["options"]
    assert len(opts) >= 2 and "start" in opts[0] and "provider_name" in opts[0]

    ctx2 = PipelineContext(encounter_id="E1", input_data=dict(ctx.input_data))
    ctx2.add_decision(_pick("0"))
    done = await _orch().run(ctx2)
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["appointment"]["status"] == "booked"
    assert is_valid_npi(done.output["selected_npi"])
    assert done.output["appointment"]["slot"]["start"] == opts[0]["start"]
    assert len(done.output["candidates"]) == 2


async def test_eligibility_is_verified_pre_visit():
    """Coverage must be confirmed in the scheduling domain, before the visit — it is
    what makes the treatment estimate (and therefore the checkout collection)
    accurate. Verifying it on the day of service would be too late to price the visit.
    """
    data = {"patient_id": "PAT-001", "request_text": "tooth pain"}
    ctx = PipelineContext(encounter_id="E5", input_data=dict(data))
    ctx.add_decision(_pick("0"))
    done = await _orch().run(ctx)
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["eligibility_verified"] is True
    assert done.output["coverage"]["active"] is True


async def test_eligibility_falls_back_to_insurance_on_file():
    """An absent payer_id means "use what's in the chart" (returning patient); an
    explicitly empty payer_id means uninsured. The two must not collapse."""
    on_file = PipelineContext(encounter_id="E6", input_data={
        "patient_id": "PAT-001", "request_text": "tooth pain"})       # payer_id absent
    on_file.add_decision(_pick("0"))
    res = await _orch().run(on_file)
    assert res.output["coverage"]["active"] is True

    uninsured = PipelineContext(encounter_id="E7", input_data={
        "patient_id": "PAT-001", "request_text": "tooth pain",
        "payer_id": "", "member_id": ""})                              # explicitly none
    uninsured.add_decision(_pick("0"))
    res2 = await _orch().run(uninsured)
    assert res2.output["coverage"]["active"] is False


async def test_referral_gate_precedes_slot_pick():
    orch = _orch()
    data = {"patient_id": "PAT-001", "request_text": "cardiology follow up", "requires_referral": True}
    paused = await orch.run(PipelineContext(encounter_id="E2", input_data=dict(data)))
    assert paused.gate.gate_id == "scheduling.referral"

    ctx = PipelineContext(encounter_id="E2", input_data=dict(data))
    ctx.add_decision(GateDecision(gate_id="scheduling.referral", approved=True, actor="Dr. Nair, MD"))
    ctx.add_decision(_pick("1"))
    done = await orch.run(ctx)
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["appointment"]["status"] == "booked"


async def test_unstaffed_specialty_degrades_instead_of_aborting():
    """A specialty the directory cannot staff must NOT kill the encounter.

    "skin rash" heuristically parses to Dermatology, which no seeded provider
    covers. Previously this failed scheduling and, because scheduling aborts on
    failure, the whole encounter died. It must now degrade to primary care and
    say so, rather than fail.
    """
    res = await _orch().run(PipelineContext(encounter_id="E3", input_data={
        "patient_id": "PAT-002", "request_text": "I have a skin rash",
    }))
    assert res.status != PipelineStatus.FAILED
    assert not res.errors
    # reached the patient's slot pick, meaning a provider was found
    assert res.status == PipelineStatus.AWAITING_HUMAN
    assert res.gate.gate_id == "scheduling.slot_selection"
    assert res.gate.data["options"]


async def test_matcher_fails_only_when_directory_is_empty():
    """The one case that SHOULD still fail: nothing bookable anywhere."""
    from src.agents.scheduling.provider_matcher import ProviderMatcher

    class EmptyDirectory:
        async def find(self, specialty, accepting_new=True):
            return []

        async def get(self, npi):
            return None

        async def specialties(self):
            return []

    class Reg:
        directory = EmptyDirectory()

    ctx = PipelineContext(encounter_id="E4", input_data={})
    ctx.results["request_parser"] = {"specialty": "General Dentistry"}
    res = await ProviderMatcher(Reg()).execute(ctx)
    assert res.status == "failed"
    assert "no bookable provider" in (res.error or "")
