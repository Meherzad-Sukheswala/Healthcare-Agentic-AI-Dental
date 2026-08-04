"""
src/integrations/synthea.py

Loads Synthea-generated FHIR bundles (data/synthea/output/fhir/*.json) into
PatientRecord objects to seed the sandbox EHR with realistic, clinically-coherent
histories. If no Synthea output is present, returns {} and the built-in seed
patients are used instead — so the demo works with or without Synthea installed.

To generate data:
    java -jar synthea-with-dependencies.jar -p 25 --exporter.fhir.export true
then copy output/fhir/*.json into data/synthea/output/fhir/.
"""
from __future__ import annotations

import glob
import json
import os

from src.logging_setup import get_logger
from src.shared.base_types import CodedConcept

from .models import PatientRecord

log = get_logger(__name__)

DEFAULT_DIR = os.path.join("data", "synthea", "output", "fhir")


def _extract_patient(bundle: dict) -> PatientRecord | None:
    patient = None
    conditions: list[CodedConcept] = []
    medications: list[CodedConcept] = []
    allergies: list[str] = []
    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})
        rtype = res.get("resourceType")
        if rtype == "Patient" and patient is None:
            patient = res
        elif rtype == "Condition":
            c = ((res.get("code") or {}).get("coding") or [{}])[0]
            if c.get("code"):
                conditions.append(CodedConcept(system=c.get("system", ""), code=c["code"], display=c.get("display", "")))
        elif rtype in ("MedicationRequest", "MedicationStatement"):
            c = ((res.get("medicationCodeableConcept") or {}).get("coding") or [{}])[0]
            if c.get("code"):
                medications.append(CodedConcept(system=c.get("system", ""), code=c["code"], display=c.get("display", "")))
        elif rtype == "AllergyIntolerance":
            txt = ((res.get("code") or {}).get("text")) or ""
            if txt:
                allergies.append(txt)
    if patient is None:
        return None
    name = (patient.get("name") or [{}])[0]
    return PatientRecord(
        patient_id=str(patient.get("id", "")),
        first_name=" ".join(name.get("given", []) or []) or "Unknown",
        last_name=name.get("family", "Unknown"),
        birth_date=patient.get("birthDate", ""),
        sex=patient.get("gender", "unknown"),
        allergies=allergies[:10],
        medications=medications[:10],
        conditions=conditions[:10],
        source="synthea",
    )


def load_synthea_patients(directory: str = DEFAULT_DIR) -> dict[str, PatientRecord]:
    if not os.path.isdir(directory):
        return {}
    out: dict[str, PatientRecord] = {}
    for path in glob.glob(os.path.join(directory, "*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                bundle = json.load(fh)
        except (OSError, ValueError):
            continue
        rec = _extract_patient(bundle)
        if rec and rec.patient_id:
            out[rec.patient_id] = rec
    log.info("synthea_loaded", count=len(out), directory=directory)
    return out
