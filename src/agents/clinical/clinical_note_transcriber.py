"""
Clinical Note Transcriber (single task: signed prose -> structured clinical data). PARTIAL.

This is the AI step the dentist is actually buying. They sign a chart note; this turns
it into the structured facts everything downstream needs:

  * per-tooth diagnoses, in universal tooth numbering, each with an ICD-10-CM code
  * the measurable findings a payer's consultant looks for (probing depths, BOP %,
    periapical radiolucency size, ridge width, maximum opening)
  * the clinical signs that justify the procedure (non-responsive to cold, tenderness
    to percussion, recurrent caries, subgingival calculus, ...)

Why PARTIAL and not FULL: the transcription is derived from a human-signed note and is
consumed by a human-reviewed treatment plan and a coder-reviewed claim. Nothing here
is autonomous in the sense of unreviewed.

Why per-tooth rather than one diagnosis per encounter: that is how a dental claim
works. The 2024 ADA claim form carries up to four diagnosis codes (item 34a) and a
per-procedure-line Diagnosis Code Pointer (item 29a), and Open Dental attaches up to
four ICD-10 codes to each procedure with one flagged as principal. A single
encounter-level diagnosis cannot express an ordinary two-problem visit.

The deterministic fallback does real work rather than echoing: it reads tooth numbers
and codes straight out of the note text, so the offline demo produces the same shape
of output as a live model.
"""
from __future__ import annotations

import json

from src.core.llm import LLMMessage, LLMRequest
from src.core.orchestrator import Agent, AgentResult
from src.shared.dental_text import extract_findings, extract_icd10, extract_teeth, split_soap
from src.shared.enums import Automation
from src.shared.medical_codes import is_valid_icd10

_SYSTEM = (
    "You are a dental clinical-documentation assistant. Read the dentist's signed "
    "chart note and transcribe it into STRICT JSON: "
    '{"diagnoses": [{"tooth": str, "icd10": str, "display": str}], '
    '"principal_icd10": str, "summary": str}. '
    "Use universal tooth numbering (1-32, or A-T for primary teeth); use an empty "
    "string for findings that are not tooth-specific (periodontal quadrants, TMJ). "
    "Diagnose ONLY the teeth named in the assessment. Teeth mentioned elsewhere as "
    "context — sound adjacent teeth, potential abutments — are not diagnoses. "
    "Transcribe only what the dentist wrote — never add a diagnosis they did not state."
)

# ICD-10 -> human-readable display, for codes this pipeline works with.
_DISPLAY = {
    "Z01.20": "Encounter for dental examination and cleaning without abnormal findings",
    "K04.7": "Periapical abscess without sinus tract",
    "K04.1": "Necrosis of pulp",
    "K05.10": "Chronic gingivitis, plaque induced",
    "K02.9": "Dental caries, unspecified",
    "M26.60": "Temporomandibular joint disorder, unspecified",
    "K08.409": "Partial loss of teeth, unspecified cause, unspecified class",
    "K08.9": "Disorder of teeth and supporting structures, unspecified",
}


class ClinicalNoteTranscriber(Agent):
    name = "clinical_note_transcriber"
    automation = Automation.PARTIAL

    def __init__(self, llm):
        self.llm = llm

    def _heuristic(self, note: str, confirmed: str) -> dict:
        """Parse the note directly — tooth numbers and codes are written in the prose.

        Teeth are read from the ASSESSMENT section, not the whole note. A dentist names
        plenty of teeth they are not diagnosing: sound adjacent teeth, candidate bridge
        abutments, teeth checked and found normal. Diagnosing all of them would put
        "partial edentulism" on the two healthy neighbours of an implant site — which is
        exactly the kind of thing a dentist reading this output would catch instantly.
        Falls back to the whole note when the dentist didn't use SOAP headers.
        """
        code = extract_icd10(note) or confirmed
        display = _DISPLAY.get(code, "Dental diagnosis")
        assessment = split_soap(note).get("assessment", "")
        teeth = extract_teeth(assessment) or (extract_teeth(note) if not assessment else [])
        if teeth:
            diagnoses = [{"tooth": t, "icd10": code, "display": display} for t in teeth]
        else:
            # periodontal, TMJ and whole-mouth findings are not tooth-specific
            diagnoses = [{"tooth": "", "icd10": code, "display": display}]
        return {
            "diagnoses": diagnoses,
            "principal_icd10": code,
            "summary": assessment or display,
        }

    async def execute(self, ctx) -> AgentResult:
        signoff = ctx.get_result("diagnosis_signoff")
        note = signoff.get("clinical_note", "") or ""
        confirmed = signoff.get("confirmed_icd10", "")

        heuristic = self._heuristic(note, confirmed)
        resp = await self.llm.complete(LLMRequest(
            system_prompt=_SYSTEM, messages=[LLMMessage.user(note or confirmed)],
            agent_name=self.name, sandbox_response=json.dumps(heuristic),
        ))
        try:
            parsed = json.loads(resp.content)
        except (json.JSONDecodeError, TypeError):
            parsed = heuristic

        # Keep only well-formed codes; never let a hallucinated code reach a claim.
        diagnoses = [d for d in parsed.get("diagnoses", []) if is_valid_icd10(d.get("icd10", ""))]
        if not diagnoses:
            diagnoses = heuristic["diagnoses"]

        principal = parsed.get("principal_icd10", "")
        if not is_valid_icd10(principal):
            principal = diagnoses[0]["icd10"]

        # de-duplicate to the max 4 codes an ADA claim can carry (item 34a)
        codes: list[str] = []
        for d in diagnoses:
            if d["icd10"] not in codes:
                codes.append(d["icd10"])
        codes = codes[:4]
        if principal in codes:                      # principal must sit at pointer "A"
            codes.remove(principal)
        codes.insert(0, principal)

        teeth = [d["tooth"] for d in diagnoses if d.get("tooth")]
        return AgentResult.completed({
            "diagnoses": diagnoses,
            "principal_icd10": principal,
            "claim_diagnosis_codes": codes[:4],
            "teeth": teeth,
            "primary_tooth": teeth[0] if teeth else "",
            "findings": extract_findings(note),
            "summary": parsed.get("summary", heuristic["summary"]),
            "transcribed_from_note": bool(note),
        })
