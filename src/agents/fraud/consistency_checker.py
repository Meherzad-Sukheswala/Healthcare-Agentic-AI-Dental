"""
Consistency Checker (single task: cross-domain clinical/billing consistency). FULL.

The only LLM-powered fraud agent, with a deterministic sandbox fallback and graceful
degradation — if the model errors, it treats the encounter as consistent (never
blocks). Flags obvious diagnosis/medication mismatches.
"""
from __future__ import annotations

import json

from src.core.llm import LLMMessage, LLMRequest
from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

_SYSTEM = (
    "You are a healthcare fraud consistency reviewer. Given a diagnosis and the "
    'medications billed, return STRICT JSON {"consistent": bool, "reason": str}.'
)

# very small demo map: ICD-10 prefix -> plausible RxNorm codes
_PLAUSIBLE = {
    # medical-history codes (still legitimate on a dental chart's problem list)
    "I10": {"29046"},          # hypertension -> lisinopril
    "I48": {"11289", "6918"},  # afib -> warfarin, metoprolol
    "E78": {"36567"},          # hyperlipidemia -> simvastatin
    # dental presenting-diagnosis codes — antibiotics AND/OR analgesics are both
    # legitimate for an infection (pain-only management pending treatment is normal
    # dental practice, not a fraud signal); only unrelated systemic meds should flag
    "K04": {"723", "2582", "6922", "161", "5640", "7804"},  # periapical abscess ->
    #        amoxicillin, clindamycin, metronidazole, acetaminophen, ibuprofen, oxycodone
    "K05": {"6922", "723", "161", "5640"},  # gingivitis/periodontitis ->
    #        metronidazole, amoxicillin, acetaminophen, ibuprofen
    "M26": {"5640", "161"},          # TMJ disorder -> ibuprofen, acetaminophen (not an antibiotic)
}


class ConsistencyChecker(Agent):
    name = "consistency_checker"
    automation = Automation.FULL

    def __init__(self, llm):
        self.llm = llm

    def _heuristic(self, dx: str, rxcuis: list[str]) -> dict:
        prefix = dx.split(".")[0] if dx else ""
        plausible = _PLAUSIBLE.get(prefix)
        if not plausible or not rxcuis:
            return {"consistent": True, "reason": "insufficient data"}
        mismatch = [r for r in rxcuis if r not in plausible]
        if mismatch:
            return {"consistent": False, "reason": f"meds {mismatch} atypical for {dx}"}
        return {"consistent": True, "reason": "meds match diagnosis"}

    async def execute(self, ctx) -> AgentResult:
        dx = ctx.input_data.get("diagnosis_icd10", "")
        rxcuis = [p.get("rxcui", "") for p in ctx.input_data.get("prescriptions", []) or []]
        heuristic = self._heuristic(dx, rxcuis)
        try:
            resp = await self.llm.complete(LLMRequest(
                system_prompt=_SYSTEM,
                messages=[LLMMessage.user(json.dumps({"dx": dx, "rxcuis": rxcuis}))],
                agent_name=self.name, sandbox_response=json.dumps(heuristic),
            ))
            parsed = json.loads(resp.content)
        except Exception:                       # graceful degradation — never block
            parsed = {"consistent": True, "reason": "checker unavailable"}
        consistent = bool(parsed.get("consistent", True))
        return AgentResult.completed({
            "consistent": consistent,
            "reason": parsed.get("reason", ""),
            "signals": [] if consistent else ["dx_med_mismatch"],
            "risk_points": 0 if consistent else 25,
        })
