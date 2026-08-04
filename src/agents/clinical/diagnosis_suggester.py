"""
Diagnosis Suggester (single task: AI proposes a differential). PARTIAL.

LLM-backed decision SUPPORT only — the dentist owns the diagnosis at the next
(sign-off) gate. Deterministic sandbox fallback keeps demos reproducible.

Also supplies the DRAFT CHART NOTE the dentist sees pre-filled at that gate. In a
real practice this text arrives from dictation or an ambient scribe (Bola AI,
Overjet Voice, Denti.AI) rather than being typed from scratch; the dentist's job is
to correct and sign it, not to author it. Serving the draft from here — rather than
hard-coding it in the UI — keeps the note keyed to the actual case and means the
front end stays dumb. See src/shared/dental_text.py for the notes themselves.
"""
from __future__ import annotations

import json

from src.core.llm import LLMMessage, LLMRequest
from src.core.orchestrator import Agent, AgentResult
from src.shared.dental_text import DEFAULT_DRAFT_NOTE, DRAFT_NOTES
from src.shared.enums import Automation

_SYSTEM = (
    "You are a clinical decision-support assistant. Given symptoms, propose a "
    'differential as STRICT JSON: {"differential": [{"icd10": str, "display": str, '
    '"confidence": float}], "primary_icd10": str}. Do NOT state a definitive diagnosis.'
)

# chief-complaint keyword -> (ICD-10-CM, display)
_MAP = [
    # The hygiene / recall visit is the most common appointment in a dental practice, so
    # it is matched FIRST — a patient saying "cleaning" is not presenting a complaint.
    (("cleaning", "prophylaxis", "prophy", "hygiene", "recall", "six month", "6 month"),
     ("Z01.20", "Encounter for dental examination and cleaning without abnormal findings")),
    (("implant", "bone graft", "edentulous", "missing tooth"),
     ("K08.409", "Partial loss of teeth, unspecified cause, unspecified class")),
    (("swelling", "swollen", "facial swelling", "throbbing"), ("K04.7", "Periapical abscess without sinus tract")),
    (("tooth pain", "toothache", "tooth ache"), ("K04.7", "Periapical abscess without sinus tract")),
    (("bleeding gums", "gum", "gingiva"), ("K05.10", "Chronic gingivitis, plaque induced")),
    (("sensitivity", "sensitive tooth", "cold sensitivity"), ("K02.9", "Dental caries, unspecified")),
    (("jaw pain", "jaw clicking", "tmj", "jaw popping"), ("M26.60", "Temporomandibular joint disorder, unspecified")),
]


class DiagnosisSuggester(Agent):
    name = "diagnosis_suggester"
    automation = Automation.PARTIAL

    def __init__(self, llm):
        self.llm = llm

    def _heuristic(self, symptoms: list[str]) -> dict:
        blob = " ".join(symptoms).lower()
        for keys, (icd, disp) in _MAP:
            if any(k in blob for k in keys):
                return {"differential": [{"icd10": icd, "display": disp, "confidence": 0.72}],
                        "primary_icd10": icd}
        return {"differential": [{"icd10": "K08.9",
                                  "display": "Disorder of teeth and supporting structures, unspecified",
                                  "confidence": 0.4}],
                "primary_icd10": "K08.9"}

    async def execute(self, ctx) -> AgentResult:
        symptoms = ctx.get_result("symptom_recorder").get("symptoms", [])
        heuristic = self._heuristic(symptoms)
        resp = await self.llm.complete(LLMRequest(
            system_prompt=_SYSTEM, messages=[LLMMessage.user(json.dumps(symptoms))],
            agent_name=self.name, sandbox_response=json.dumps(heuristic),
        ))
        try:
            parsed = json.loads(resp.content)
        except (json.JSONDecodeError, TypeError):
            parsed = heuristic
        primary = parsed.get("primary_icd10", "R69")
        return AgentResult.completed({
            "differential": parsed.get("differential", []),
            "primary_icd10": primary,
            # pre-filled chart note for the sign-off gate — editable by the dentist
            "draft_note": DRAFT_NOTES.get(primary, DEFAULT_DRAFT_NOTE),
        })
