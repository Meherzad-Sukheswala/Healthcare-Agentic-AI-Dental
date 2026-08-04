"""
The documentation -> claim chain: the dentist signs a chart note, and the AI turns it
into per-tooth diagnoses, ADA claim diagnosis codes with per-line pointers, and the
narrative a payer's dental consultant reads.

These are the assertions a dentist watching a demo would actually check: that the tooth
in the plan matches the tooth in their note, that healthy teeth they merely mentioned
don't get diagnosed, and that editing the note changes the output.
"""
from src.agents.clinical import ClinicalOrchestrator
from src.config import Settings
from src.core.llm import LLMClient
from src.core.orchestrator import GateDecision, PipelineContext
from src.integrations import build_registry
from src.integrations.seed_data import PROVIDERS
from src.shared.dental_text import (
    DRAFT_NOTES,
    extract_findings,
    extract_icd10,
    extract_teeth,
    narrative_for,
    split_soap,
)
from src.shared.enums import PipelineStatus

NPI = PROVIDERS[0].npi
COMMERCIAL = {"active": True, "payer_type": "commercial", "annual_max_cents": 150000,
              "annual_max_used_cents": 0,
              "category_coverage_pct": {"preventive": 1.0, "basic": 0.8, "major": 0.5}}
MEDICARE = dict(COMMERCIAL, payer_type="medicare", requires_diagnosis_codes=True)


def _orch():
    s = Settings(_env_file=None)
    return ClinicalOrchestrator(registry=build_registry(s), llm_client=LLMClient(s))


def _base(**over):
    data = {"patient_id": "PAT-001", "selected_npi": NPI,
            "chief_complaint": "tooth pain and swelling",
            "current_medications": [], "allergies": [], "prescribe": [],
            "coverage": dict(COMMERCIAL)}
    data.update(over)
    return data


def _signed(note):
    """The dentist signs the chart note — this is exactly what the UI posts."""
    return GateDecision(gate_id="clinical.diagnosis", approved=True,
                        actor="Dr. A. Rao, DDS", note=note)


def _approvals(note):
    return [_signed(note),
            GateDecision(gate_id="clinical.treatment_plan", approved=True, actor="Dr. A. Rao, DDS"),
            GateDecision(gate_id="clinical.treatment_consent", approved=True, actor="Maria Garcia")]


async def _run(data, note, eid="DOC"):
    ctx = PipelineContext(encounter_id=eid, input_data=dict(data))
    for d in _approvals(note):
        ctx.add_decision(d)
    return await _orch().run(ctx)


# --------------------------------------------------------------- the extractors
def test_extract_teeth_reads_universal_numbering():
    assert extract_teeth("Tooth #30 - large MOD amalgam") == ["30"]
    assert extract_teeth("#18 and #20 sound and unrestored") == ["18", "20"]
    assert extract_teeth("tooth 14 occlusal caries") == ["14"]
    assert extract_teeth("no teeth referenced here") == []


def test_extract_icd10_does_not_mistake_cdt_codes_for_diagnoses():
    """D3330 and D6010 start with a letter+digits and would match a naive ICD-10
    pattern. Pulling a CDT procedure code in as a diagnosis would corrupt the claim."""
    assert extract_icd10("Dx: periapical abscess K04.7") == "K04.7"
    assert extract_icd10("P: RCT D3330, crown D2740, implant D6010") == ""
    assert extract_icd10("plan D3330 for K04.7 today") == "K04.7"
    assert extract_icd10("") == ""


def test_split_soap_finds_the_assessment_section():
    soap = split_soap(DRAFT_NOTES["K04.7"])
    assert "throbbing pain" in soap["subjective"]
    assert "periapical radiolucency" in soap["objective"]
    assert "K04.7" in soap["assessment"]
    assert "RCT #30" in soap["plan"]


def test_extract_findings_pulls_the_measurements_a_payer_wants():
    f = extract_findings(DRAFT_NOTES["K04.7"])
    assert f["measurements"]["periapical_radiolucency"] == "3"
    assert "non_responsive_to_cold" in f["signs"]
    assert "percussion_tender" in f["signs"]

    perio = extract_findings(DRAFT_NOTES["K05.10"])
    assert perio["measurements"]["bop_pct"] == "34"
    assert "subgingival_calculus" in perio["signs"]


# --------------------------------------------------------------- transcription
async def test_signed_note_is_transcribed_into_per_tooth_diagnoses():
    done = await _run(_base(), DRAFT_NOTES["K04.7"], eid="DOC1")
    assert done.status == PipelineStatus.COMPLETED

    t = done.output["transcription"]
    assert t["transcribed_from_note"] is True
    assert t["principal_icd10"] == "K04.7"
    assert t["diagnoses"] == [{"tooth": "30", "icd10": "K04.7",
                               "display": "Periapical abscess without sinus tract"}]
    # the signed note is what gets persisted, not a machine summary of it
    assert done.output["clinical_note"] == DRAFT_NOTES["K04.7"]
    assert done.output["note_signed_by"] == "Dr. A. Rao, DDS"


async def test_treatment_plan_uses_the_tooth_from_the_dentists_note():
    """A plan that treats a different tooth from the chart note is the first thing a
    dentist would catch. #30 in the note must be #30 in the plan."""
    done = await _run(_base(), DRAFT_NOTES["K04.7"], eid="DOC2")
    items = done.output["treatment_plan"]["items"]
    assert done.output["treatment_plan"]["tooth_from_chart_note"] is True
    assert [i["cdt"] for i in items] == ["D3330", "D2740"]
    assert {i["tooth"] for i in items} == {"30"}          # both procedures, same tooth


async def test_context_teeth_in_the_note_are_not_diagnosed():
    """The implant note names #18 and #20 as SOUND adjacent teeth. Diagnosing them
    would put partial edentulism on two healthy neighbours."""
    data = _base(chief_complaint="evaluation for dental implant and bone graft")
    done = await _run(data, DRAFT_NOTES["K08.409"], eid="DOC3")
    teeth = [d["tooth"] for d in done.output["transcription"]["diagnoses"]]
    assert teeth == ["19"]                                # only the edentulous site
    assert "18" not in teeth and "20" not in teeth
    assert [i["cdt"] for i in done.output["treatment_plan"]["items"]] == ["D7953", "D6010", "D6058"]


async def test_non_tooth_specific_diagnosis_stays_non_tooth_specific():
    """Periodontal disease is diagnosed by quadrant/sextant, not by tooth, and the
    SRP code is quadrant-level — so no tooth number should be invented."""
    data = _base(chief_complaint="bleeding gums")
    done = await _run(data, DRAFT_NOTES["K05.10"], eid="DOC4")
    assert done.output["transcription"]["diagnoses"][0]["tooth"] == ""
    items = done.output["treatment_plan"]["items"]
    assert [i["cdt"] for i in items] == ["D4341"]
    assert items[0]["tooth"] == ""


async def test_dentist_editing_the_note_overrides_the_ai_suggestion():
    """The dentist writes the code inline in their own prose — no special field."""
    amended = DRAFT_NOTES["K04.7"].replace("K04.7", "K04.1")   # necrosis of pulp instead
    done = await _run(_base(), amended, eid="DOC5")
    assert done.output["diagnosis"]["code_from_dentist_note"] is True
    assert done.output["icd10"] == "K04.1"
    assert done.output["transcription"]["principal_icd10"] == "K04.1"


async def test_amending_to_an_adjacent_code_keeps_a_clinically_sensible_plan():
    """K04.1 (necrosis of pulp) still needs a root canal. A dentist amending the code
    to a neighbour in the same ICD-10 family must not watch the plan collapse to an
    exam — every K04.x is a pulp/periapical disease and implies endodontic treatment."""
    amended = DRAFT_NOTES["K04.7"].replace("K04.7", "K04.1")
    done = await _run(_base(), amended, eid="DOC13")
    plan = done.output["treatment_plan"]
    assert [i["cdt"] for i in plan["items"]] == ["D3330", "D2740"]
    assert plan["exact_protocol_match"] is False        # matched by family, and says so
    assert plan["matched_on_icd10"] == "K04.7"
    assert done.output["cdt"] == "D3330"


async def test_hygiene_recall_visit_bills_prophy_and_periodic_exam():
    """The hygiene visit is the most common appointment in a dental practice. It must
    produce the codes a real recall visit bills — and no tooth number, since a
    prophylaxis and a periodic evaluation are both whole-mouth."""
    data = _base(chief_complaint="routine cleaning and recall")
    done = await _run(data, DRAFT_NOTES["Z01.20"], eid="DOC15")
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["transcription"]["principal_icd10"] == "Z01.20"
    assert done.output["cdt_codes"] == ["D0120", "D1110"]
    assert all(i["tooth"] == "" for i in done.output["treatment_plan"]["items"])
    # preventive codes are paid on frequency, not justification — no narrative needed
    assert done.output["narratives"] == []


async def test_unspecified_diagnosis_still_declines_to_invent_a_procedure():
    """The family fallback must not make K08.9 (unspecified) produce a plan — it is
    deliberately unmapped, and K08.4xx (partial loss of teeth) must stay separate."""
    done = await _run(_base(chief_complaint="annual checkup"), DRAFT_NOTES["K08.9"], eid="DOC14")
    assert done.output["treatment_plan"]["items"] == []
    assert done.output["cdt"] in ("D0140", "D0150")


async def test_unsigned_note_falls_back_to_the_ai_suggestion():
    """A caller that approves the gate without a note must not break the encounter."""
    done = await _run(_base(), "", eid="DOC6")
    assert done.status == PipelineStatus.COMPLETED
    assert done.output["diagnosis"]["code_from_dentist_note"] is False
    assert done.output["icd10"] == "K04.7"                 # the suggester's primary


# --------------------------------------------------------------- claim coding
async def test_diagnosis_codes_carry_ada_item_29a_line_pointers():
    done = await _run(_base(), DRAFT_NOTES["K04.7"], eid="DOC7")
    assert done.output["diagnosis_codes"] == ["K04.7"]     # item 34a, principal at "A"
    lines = done.output["line_diagnoses"]                  # item 29a
    assert len(lines) == 2                                 # RCT + crown
    assert {ln["cdt"] for ln in lines} == {"D3330", "D2740"}
    for ln in lines:
        assert ln["diagnosis_pointer"] == "A"
        assert ln["icd10"] == "K04.7"
        assert ln["tooth"] == "30"


async def test_diagnosis_submission_is_required_for_medicare_not_commercial():
    """Medicare rejects dental claims without a valid ICD-10; most commercial dental
    plans accept one but adjudicate on CDT."""
    commercial = await _run(_base(), DRAFT_NOTES["K04.7"], eid="DOC8")
    assert commercial.output["diagnosis_submission_required"] is False
    assert "adjudicates on CDT" in commercial.output["diagnosis_submission_reason"]

    medicare = await _run(_base(coverage=dict(MEDICARE)), DRAFT_NOTES["K04.7"], eid="DOC9")
    assert medicare.output["diagnosis_submission_required"] is True
    assert "Medicare" in medicare.output["diagnosis_submission_reason"]


# --------------------------------------------------------------- narratives
async def test_narrative_is_written_per_procedure_and_is_tooth_specific():
    done = await _run(_base(), DRAFT_NOTES["K04.7"], eid="DOC10")
    narratives = {n["cdt"]: n for n in done.output["narratives"]}
    assert set(narratives) == {"D3330", "D2740"}
    for n in narratives.values():
        assert n["tooth"] == "30"
        assert "#30" in n["text"] or "Tooth 30" in n["text"]


async def test_crown_narrative_makes_the_leat_argument():
    """A crown claim is denied unless the narrative says why a filling wouldn't do.
    That argument is the single thing a payer's consultant is looking for."""
    text = narrative_for("D2740", "30")
    assert "#30" in text
    assert "would not provide adequate structural support" in text
    assert "recurrent caries" in text


async def test_srp_narrative_cites_probing_depths_and_bone_loss():
    text = narrative_for("D4341")
    assert "4-5mm" in text
    assert "bleeding on probing" in text
    assert "bone loss" in text
    assert "prophylaxis would not address" in text


async def test_attachments_recommended_match_the_procedures_performed():
    endo = await _run(_base(), DRAFT_NOTES["K04.7"], eid="DOC11")
    recommended = " ".join(endo.output["attachments_recommended"]).lower()
    assert "preoperative periapical radiograph" in recommended
    assert "postoperative periapical radiograph" in recommended

    perio = await _run(_base(chief_complaint="bleeding gums"), DRAFT_NOTES["K05.10"], eid="DOC12")
    perio_rec = " ".join(perio.output["attachments_recommended"]).lower()
    assert "periodontal charting" in perio_rec
    assert "bone loss" in perio_rec


async def test_every_draft_note_names_the_code_it_is_filed_under():
    """Each pre-filled note must contain its own diagnosis code, or the demo would
    silently fall back to the model's guess instead of reading the dentist's note."""
    for code, note in DRAFT_NOTES.items():
        assert extract_icd10(note) == code, f"{code} note does not state its own code"
        assert split_soap(note)["assessment"], f"{code} note has no assessment section"
