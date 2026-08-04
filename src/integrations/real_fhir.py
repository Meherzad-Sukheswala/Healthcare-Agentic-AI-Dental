"""
src/integrations/real_fhir.py

The ONE real external integration for the demo: a live read against a public
FHIR R4 test server (e.g. https://hapi.fhir.org/baseR4). Implements EHRPort so it
is a drop-in for SandboxEHR. Read-only: writes fall back to a simulated id, since
public test servers are not a place to persist PHI.

Everything is wrapped defensively — if the network is unavailable the caller can
catch and fall back to the sandbox, so a live demo never hard-fails.
"""
from __future__ import annotations

import httpx

from src.config import Settings, get_settings
from src.logging_setup import get_logger
from src.shared.base_types import CodedConcept

from .models import PatientRecord

log = get_logger(__name__)


class RealFHIREHR:
    """EHRPort backed by a real public FHIR R4 server."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.base = self.settings.fhir_public_base_url.rstrip("/")

    async def get_patient(self, patient_id: str) -> PatientRecord | None:
        url = f"{self.base}/Patient/{patient_id}"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0)) as c:
                resp = await c.get(url, headers={"Accept": "application/fhir+json"})
        except httpx.HTTPError as exc:
            log.warning("fhir_public_unreachable", error=str(exc))
            return None
        if resp.status_code != 200:
            log.warning("fhir_public_status", status=resp.status_code)
            return None
        res = resp.json()
        name = (res.get("name") or [{}])[0]
        given = " ".join(name.get("given", []) or [])
        conditions = await self._conditions(patient_id)
        return PatientRecord(
            patient_id=str(res.get("id", patient_id)),
            first_name=given or "Unknown",
            last_name=name.get("family", "Unknown"),
            birth_date=res.get("birthDate", ""),
            sex=res.get("gender", "unknown"),
            conditions=conditions,
            source="fhir_public",
        )

    async def _conditions(self, patient_id: str) -> list[CodedConcept]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0)) as c:
                resp = await c.get(
                    f"{self.base}/Condition",
                    params={"patient": patient_id, "_count": "5"},
                    headers={"Accept": "application/fhir+json"},
                )
            entries = resp.json().get("entry", []) if resp.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            return []
        out: list[CodedConcept] = []
        for e in entries:
            coding = (((e.get("resource") or {}).get("code") or {}).get("coding") or [{}])[0]
            if coding.get("code"):
                out.append(CodedConcept(system=coding.get("system", "unknown"),
                                        code=coding["code"], display=coding.get("display", "")))
        return out

    async def write_clinical_note(self, patient_id: str, note: str) -> str:
        # public server is read-only for our purposes
        return "DocumentReference/simulated-write"
