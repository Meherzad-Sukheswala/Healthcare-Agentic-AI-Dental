"""
src/integrations/registry.py

ServiceRegistry — the dependency-injection container every agent reads from.
Agents never construct a service; they receive the registry and call, e.g.,
`registry.eligibility.check(...)`. Swapping sandbox -> real is done here, once.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.config import Settings, get_settings
from src.logging_setup import get_logger

from . import sandbox
from .idempotency import wrap_registry
from .real_fhir import RealFHIREHR

log = get_logger(__name__)


@dataclass
class ServiceRegistry:
    ehr: Any
    eligibility: Any
    prior_auth: Any
    claims: Any
    directory: Any
    drug_info: Any
    pharmacy: Any
    epcs: Any
    pdmp: Any
    payment: Any
    schedule: Any
    # Populated by wrap_registry(): the encounter-scoped side-effect ledger.
    ledger: Any = None


def build_registry(settings: Settings | None = None) -> ServiceRegistry:
    """Construct the registry from settings. EHR read can be real or sandbox.

    The returned registry is wrapped for encounter-scoped idempotency: mutating
    vendor calls run at most once per encounter no matter how many times the
    pipeline replays through a human gate. See integrations/idempotency.py.
    """
    s = settings or get_settings()
    ehr = RealFHIREHR(s) if s.ehr_mode == "fhir_public" else sandbox.SandboxEHR()
    log.info("service_registry_built", ehr_mode=s.ehr_mode)
    return wrap_registry(ServiceRegistry(
        ehr=ehr,
        eligibility=sandbox.SandboxEligibility(),
        prior_auth=sandbox.SandboxPriorAuth(),
        claims=sandbox.SandboxClaims(),
        directory=sandbox.SandboxProviderDirectory(),
        drug_info=sandbox.SandboxDrugInfo(),
        pharmacy=sandbox.SandboxPharmacy(),
        epcs=sandbox.SandboxEPCS(),
        pdmp=sandbox.SandboxPDMP(),
        payment=sandbox.SandboxPayment(),
        schedule=sandbox.SandboxSchedule(),
    ))
