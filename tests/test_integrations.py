"""Integration layer: DI registry, sandbox fidelity, and valid seed identifiers."""
from src.config import Settings
from src.integrations import build_registry
from src.integrations.seed_data import PRESCRIBER_DEA, PROVIDERS
from src.shared.codegen import make_dea, make_npi
from src.shared.enums import Severity
from src.shared.medical_codes import is_valid_dea, is_valid_icd10, is_valid_npi


def test_codegen_makes_valid_ids():
    assert is_valid_npi(make_npi("193456781"))
    assert is_valid_dea(make_dea("AR", "918273"))


def test_seed_data_is_wellformed():
    for p in PROVIDERS:
        assert is_valid_npi(p.npi), p.npi
    assert is_valid_dea(PRESCRIBER_DEA)


def test_registry_defaults_to_sandbox():
    reg = build_registry(Settings(_env_file=None, ehr_mode="sandbox"))
    assert reg.ehr.__class__.__name__ == "SandboxEHR"


async def test_ehr_and_eligibility():
    reg = build_registry(Settings(_env_file=None))
    pat = await reg.ehr.get_patient("PAT-001")
    assert pat and pat.last_name == "Garcia"
    assert is_valid_icd10(pat.conditions[0].code)
    cov = await reg.eligibility.check(pat.member_id, pat.payer_id, "D0140")
    assert cov.active and cov.service_covered


async def test_drug_interactions_and_prior_auth():
    reg = build_registry(Settings(_env_file=None))
    inter = await reg.drug_info.interactions(["11289", "5640"])   # warfarin + ibuprofen
    assert inter and inter[0].severity == Severity.SEVERE

    pended = await reg.prior_auth.submit("BCB-90001", "PAYER-001", "D6010", "K04.7")
    assert pended.requires_clinical_review
    approved = await reg.prior_auth.submit("BCB-90001", "PAYER-001", "D0140", "I10")
    assert not approved.requires_clinical_review


async def test_directory_pdmp_payment_epcs():
    reg = build_registry(Settings(_env_file=None))
    cards = await reg.directory.find("General Dentistry")
    assert len(cards) == 2
    report = await reg.pdmp.query("PAT-001", "CA")
    assert report.state == "CA"
    pay = await reg.payment.charge(3000, "tok_demo")
    assert pay.status == "succeeded"
    sig = await reg.epcs.sign(cards[0].npi, "RX-1", "123456")
    assert sig.signed and sig.two_factor_used
