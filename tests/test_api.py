"""API layer: health, a full encounter driven over HTTP with gate resumes, and 404s."""
from fastapi.testclient import TestClient

from src.api.app import create_app

client = TestClient(create_app())

APPROVALS = {
    "scheduling.slot_selection": {"approved": True, "actor": "Patient", "note": "0"},
    "patient.consent": {"approved": True, "actor": "Patient"},
    "clinical.diagnosis": {"approved": True, "actor": "Dr. Rao, MD"},
    "clinical.treatment_plan": {"approved": True, "actor": "Dr. Rao, MD"},
    "clinical.treatment_consent": {"approved": True, "actor": "Maria Garcia"},
    "billing.coding_qa": {"approved": True, "actor": "CDI"},
    "billing.payment_auth": {"approved": True, "actor": "Patient"},
    "pharmacy.verification": {"approved": True, "actor": "PharmD Lee"},
}


def test_ui_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Live Encounter" in r.text


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["agents"] > 60          # computed from live orchestrator step counts, not hand-maintained


def test_full_encounter_over_http():
    start = client.post("/encounters", json={
        "patient_id": "PAT-001",
        "chief_complaint": "tooth pain and swelling",
        "prescribe": [{"rx_id": "RX-1", "rxcui": "161", "ndc": "0069-2587-10", "schedule": "non_controlled"}],
        "payment_token": "tok_visa",
    })
    assert start.status_code == 200
    data = start.json()
    eid = data["encounter_id"]

    seen = []
    for _ in range(15):
        if data["status"] != "awaiting_human":
            break
        gate = data["awaiting_gate"]["gate_id"]
        seen.append(gate)
        r = client.post(f"/encounters/{eid}/resume", json={"gate_id": gate, **APPROVALS[gate]})
        assert r.status_code == 200
        data = r.json()

    assert data["status"] == "completed"
    assert seen == ["scheduling.slot_selection", "patient.consent", "clinical.diagnosis",
                    "clinical.treatment_plan", "clinical.treatment_consent",
                    "billing.coding_qa", "billing.payment_auth", "pharmacy.verification"]
    assert data["summary"]["payment_status"] == "succeeded"
    assert data["summary"]["dispensed"] is True

    # GET returns the same completed state
    got = client.get(f"/encounters/{eid}")
    assert got.status_code == 200
    assert got.json()["status"] == "completed"


def test_unknown_encounter_404():
    assert client.get("/encounters/does-not-exist").status_code == 404
    assert client.post("/encounters/nope/resume",
                       json={"gate_id": "x", "approved": True}).status_code == 404
