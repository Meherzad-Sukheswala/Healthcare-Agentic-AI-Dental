"""
Claim Narrative Writer (single task: signed note -> per-procedure claim narrative). PARTIAL.

THE HIGHEST-VALUE AI STEP IN THE CLAIM PATH
-------------------------------------------
A dental payer's consultant is a licensed dentist who explicitly cannot examine the
patient. The narrative is the only channel for what the radiograph can't show, and
inadequate or template narratives are the leading cause of dental claim denials —
"patient needs a crown on #30" gets denied; the same claim with the objective findings
and the reason a filling wouldn't hold gets paid.

Codes are the easy half: CDT is a closed vocabulary a dentist already knows. The
narrative is free text, per tooth, per encounter, and it is what the money turns on.
This is also what the real products generate (Overjet, Bola AI, CDT-code assistants
all emit "supporting narrative" alongside the code).

WHAT A PAYER WANTS IN ONE
-------------------------
  1. tooth in universal notation
  2. objective, measurable findings — probing depths, BOP %, radiolucency size, mobility
  3. a reference to the attached imaging
  4. prior treatment on the tooth and how it failed
  5. the procedure, tied to those findings
  6. why a less expensive alternative would not suffice — the LEAT argument, which is
     the specific thing that gets crowns and SRP approved

Narratives must be TOOTH-SPECIFIC and patient-specific; payers evaluate each tooth
independently and copy-pasted templates trigger denials. The templates in
src/shared/dental_text.py are per-CDT starting points that the model personalises from
the dentist's actual wording — which is why the prompt tells it to reuse the dentist's
own language rather than invent findings.

Output feeds two places: the claim's `narratives` (837D) and the attachment envelope
that carries radiographs and perio charting (NEA FastAttach / PWK segment).
"""
from __future__ import annotations

import json

from src.core.llm import LLMMessage, LLMRequest
from src.core.orchestrator import Agent, AgentResult
from src.shared.dental_text import narrative_for
from src.shared.enums import Automation

_SYSTEM = (
    "You are a dental insurance narrative writer. For each performed procedure, write "
    "ONE narrative a payer's dental consultant would accept, as STRICT JSON: "
    '{"narratives": [{"cdt": str, "tooth": str, "text": str}]}. '
    "Each narrative must state the tooth in universal numbering, the objective "
    "measurable findings, a reference to the attached imaging, and why a less "
    "expensive alternative treatment would not have been adequate. Reuse the "
    "dentist's own wording and findings from the chart note — never invent a finding "
    "that is not in the note. Keep each narrative under 120 words."
)

# Procedures that never need a narrative — routine diagnostic and preventive codes are
# paid on frequency, not on justification.
_NO_NARRATIVE_NEEDED = {"D0120", "D0272", "D0274", "D1110", "D1206", "D1208"}


class ClaimNarrativeWriter(Agent):
    name = "claim_narrative_writer"
    automation = Automation.PARTIAL

    def __init__(self, llm):
        self.llm = llm

    def _heuristic(self, performed: list[dict]) -> dict:
        return {"narratives": [
            {"cdt": i.get("cdt", ""), "tooth": i.get("tooth", ""),
             "text": narrative_for(i.get("cdt", ""), i.get("tooth", ""))}
            for i in performed if i.get("cdt", "").upper() not in _NO_NARRATIVE_NEEDED
        ]}

    async def execute(self, ctx) -> AgentResult:
        performed = ctx.get_result("procedure_documentor").get("performed_items", [])
        note = ctx.get_result("diagnosis_signoff").get("clinical_note", "")
        transcript = ctx.get_result("clinical_note_transcriber")

        if not performed:
            return AgentResult.completed({"narratives": [], "narrative_count": 0,
                                          "attachments_recommended": []})

        heuristic = self._heuristic(performed)
        payload = json.dumps({
            "chart_note": note,
            "findings": transcript.get("findings", {}),
            "diagnoses": transcript.get("diagnoses", []),
            "procedures": [{"cdt": i.get("cdt", ""), "tooth": i.get("tooth", ""),
                            "description": i.get("description", "")} for i in performed],
        })
        resp = await self.llm.complete(LLMRequest(
            system_prompt=_SYSTEM, messages=[LLMMessage.user(payload)],
            agent_name=self.name, sandbox_response=json.dumps(heuristic), max_tokens=900,
        ))
        try:
            parsed = json.loads(resp.content)
        except (json.JSONDecodeError, TypeError):
            parsed = heuristic

        narratives = [n for n in parsed.get("narratives", []) if n.get("text")]
        if not narratives:
            narratives = heuristic["narratives"]

        # What has to ride along with the narrative in the attachment envelope. This is
        # the documentation the payer will ask for if it isn't sent up front.
        recommended: list[str] = []
        codes = {i.get("cdt", "").upper() for i in performed}
        if codes & {"D3310", "D3320", "D3330"}:
            recommended += ["preoperative periapical radiograph", "postoperative periapical radiograph"]
        if codes & {"D2740", "D2750", "D2950", "D6058"}:
            recommended.append("preoperative radiograph showing remaining tooth structure")
        if codes & {"D4341", "D4342", "D4910"}:
            recommended += ["full-mouth periodontal charting (6 sites per tooth)",
                            "radiographs demonstrating bone loss"]
        if codes & {"D6010", "D7953"}:
            recommended.append("CBCT demonstrating ridge dimensions")
        if not recommended:
            recommended.append("chart note for the date of service")

        return AgentResult.completed({
            "narratives": narratives,
            "narrative_count": len(narratives),
            # de-duplicated, order preserved
            "attachments_recommended": list(dict.fromkeys(recommended)),
            "written_from_signed_note": bool(note),
        })
