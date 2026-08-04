"""
Diagnosis Sign-off (single task: the dentist confirms the diagnosis). MANUAL.

Always required, and a licensure boundary rather than a workflow preference: only a
dentist may diagnose. The AI drafts; the dentist owns what gets signed.

WHAT THE DENTIST ACTUALLY DOES HERE
-----------------------------------
They are handed a pre-filled chart note (dictation / ambient-scribe output) and they
correct and sign it. The note is the artifact — free-form clinical prose in the
shorthand dentists actually write — not a code picked from a dropdown. Whatever they
sign lands in `clinical_note`, and `clinical_note_transcriber` (the next step) is what
turns that prose into structured per-tooth diagnoses.

Two ways the dentist can change the diagnosis, both supported:
  * edit the note and write the code inline ("...consistent with K04.7...") — the
    normal case, since that is how a dentist writes;
  * leave the note alone and accept the AI's suggestion.

An ICD-10 code is pulled from anywhere in the signed note, so the dentist never has
to put it in a special field. Anything unparseable falls back to the AI suggestion
rather than failing the encounter.
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent
from src.shared.dental_text import DEFAULT_DRAFT_NOTE, extract_icd10, extract_teeth


class DiagnosisSignoff(HumanGateAgent):
    name = "diagnosis_signoff"
    gate_id = "clinical.diagnosis"

    def build_request(self, ctx) -> GateRequest:
        dx = ctx.get_result("diagnosis_suggester")
        return GateRequest(
            gate_id=self.gate_id,
            title="Dentist diagnosis sign-off",
            prompt=("Review the chart note, edit anything that is wrong, and sign. "
                    "The AI transcribes what you sign into claim codes and the "
                    "insurance narrative — it does not change your wording."),
            domain="clinical",
            data={
                "suggested": dx.get("differential", []),
                "primary_icd10": dx.get("primary_icd10", ""),
                # the editable note itself
                "draft_note": dx.get("draft_note", DEFAULT_DRAFT_NOTE),
            },
        )

    def on_approved(self, ctx, decision) -> dict:
        suggested = ctx.get_result("diagnosis_suggester").get("primary_icd10", "")
        note = (decision.note or "").strip()
        in_note = extract_icd10(note)
        return {
            "diagnosis_confirmed": True,
            "confirmed_icd10": in_note or suggested,
            # True when the dentist's own wording supplied the code, rather than the
            # encounter silently falling back to what the model guessed
            "code_from_dentist_note": bool(in_note),
            "clinical_note": note,
            "note_signed": bool(note),
            "teeth_referenced": extract_teeth(note),
            "dentist": decision.actor,
        }
