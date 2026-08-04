"""
EHR Writer (single task: persist the clinical note to the EHR). FULL.

Writes the DENTIST'S SIGNED NOTE, not a machine-generated summary of it. The note the
dentist signed at the diagnosis gate is the legal record; the codes derived from it are
metadata. Falls back to a coded summary line only when no note was signed (a caller
driving the domain without going through the gate).
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation


class EHRWriter(Agent):
    name = "ehr_writer"
    automation = Automation.FULL

    def __init__(self, registry):
        self.reg = registry

    async def execute(self, ctx) -> AgentResult:
        pid = ctx.input_data.get("patient_id", "")
        icd10 = ctx.get_result("diagnosis_coder").get("icd10", "")
        codes = ctx.get_result("procedure_documentor").get("cdt_codes", [])
        signed = ctx.get_result("diagnosis_signoff")
        header = (f"Encounter {ctx.encounter_id}: Dx {icd10}, "
                  f"Procedures {', '.join(codes) or 'none'}")
        chart_note = signed.get("clinical_note", "")
        note = f"{header}\n\n{chart_note}" if chart_note else header
        ref = await self.reg.ehr.write_clinical_note(pid, note)
        return AgentResult.completed({
            "document_ref": ref,
            "note": note,
            "signed_by": signed.get("dentist", ""),
            "includes_signed_note": bool(chart_note),
        })
