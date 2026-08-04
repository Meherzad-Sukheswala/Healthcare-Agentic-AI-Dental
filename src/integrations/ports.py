"""
src/integrations/ports.py

Adapter *ports* — the standards-shaped interfaces every domain agent talks to.
Each port has (a) a high-fidelity sandbox implementation for offline demos and
(b) a place to drop a real vendor implementation later, with zero agent changes.

Ports are typing.Protocol so implementations only need matching methods.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import (
    ClaimAck,
    ClaimAttachment,
    Coverage,
    InformationRequest,
    Dispatch,
    EPCSSignature,
    FormularyStatus,
    Interaction,
    PatientRecord,
    PaymentResult,
    PDMPReport,
    PriorAuthResult,
    Provider,
    RemittanceAdvice,
)


@runtime_checkable
class EHRPort(Protocol):
    """FHIR R4 EHR/PMS (Dentrix/Open Dental for a dental practice, Epic/Cerner for a
    hospital deployment; sandbox or public FHIR here)."""

    async def get_patient(self, patient_id: str) -> PatientRecord | None: ...
    async def write_clinical_note(self, patient_id: str, note: str) -> str: ...


@runtime_checkable
class EligibilityPort(Protocol):
    """X12 270/271 eligibility & benefits."""

    async def check(self, member_id: str, payer_id: str, service_code: str) -> Coverage: ...


@runtime_checkable
class PriorAuthPort(Protocol):
    """X12 278 prior authorization."""

    async def submit(self, member_id: str, payer_id: str, procedure_code: str, dx: str) -> PriorAuthResult: ...


@runtime_checkable
class ClaimsPort(Protocol):
    """The full claim round trip.

      submit_claim             X12 837D out, 277CA back (accepted or rejected)
      get_information_request  X12 277RFAI — the payer PENDING for documentation, or None
      send_attachment          X12 275 — documentation back, with its PWK linkage
      get_remittance           X12 835 ERA — the adjudicated result

    The middle two are the "payer wants more evidence" round trip. A real integration
    fulfils them through a dental clearinghouse and an attachment service (Vyne /
    DentalXChange / NEA FastAttach); the sandbox simulates both.
    """

    async def submit_claim(self, claim: dict) -> ClaimAck: ...
    async def get_information_request(
        self, claim: dict, control_number: str) -> InformationRequest | None: ...
    async def send_attachment(self, claim_control_number: str, documents: list[dict],
                              outstanding: list[str] | None = None) -> ClaimAttachment: ...
    async def get_remittance(self, claim: dict, control_number: str) -> RemittanceAdvice: ...


@runtime_checkable
class ProviderDirectoryPort(Protocol):
    """NPPES provider directory."""

    async def find(self, specialty: str, accepting_new: bool = True) -> list[Provider]: ...
    async def get(self, npi: str) -> Provider | None: ...
    async def specialties(self) -> list[str]: ...


@runtime_checkable
class DrugInfoPort(Protocol):
    """Drug interaction / allergy / formulary reference (FDB/Micromedex-like)."""

    async def interactions(self, rxcuis: list[str]) -> list[Interaction]: ...
    async def cross_allergies(self, rxcui: str, allergies: list[str]) -> list[str]: ...
    async def formulary(self, payer_id: str, ndc: str) -> FormularyStatus: ...


@runtime_checkable
class PharmacyPort(Protocol):
    """NCPDP SCRIPT / Surescripts pharmacy network."""

    async def send_prescription(self, order: dict) -> str: ...
    async def check_stock(self, ndc: str) -> bool: ...
    async def dispatch(self, order_id: str) -> Dispatch: ...


@runtime_checkable
class EPCSPort(Protocol):
    """DEA EPCS controlled-substance electronic signing (2-factor)."""

    async def sign(self, prescriber_npi: str, rx_id: str, otp: str) -> EPCSSignature: ...


@runtime_checkable
class PDMPPort(Protocol):
    """State Prescription Drug Monitoring Program query."""

    async def query(self, patient_id: str, state: str) -> PDMPReport: ...


@runtime_checkable
class SchedulePort(Protocol):
    """Per-provider availability calendar (working hours minus existing bookings)."""

    async def availability(self, npi: str, limit: int = 5) -> list[dict]: ...
    async def book(self, npi: str, start: str) -> bool: ...


@runtime_checkable
class PaymentPort(Protocol):
    """Healthcare-grade payment processor (never Stripe in prod)."""

    async def charge(self, amount_cents: int, token: str) -> PaymentResult: ...
