"""
src/api/app.py

FastAPI layer over the MasterOrchestrator. Endpoints:

  POST /encounters              start an encounter (runs until the first gate)
  POST /encounters/{id}/resume  supply a human decision for a gate, then continue
  GET  /encounters/{id}         current encounter state
  GET  /encounters/{id}/status  lightweight status
  GET  /health                  health check

Run: uvicorn src.api.app:app --reload --port 8000  (Swagger at /docs)
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

_WEB_INDEX = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "web", "index.html"
)

from src.config import get_settings
from src.core.llm import LLMClient
from src.core.pipeline import MasterOrchestrator
from src.integrations import build_registry
from src.logging_setup import configure_logging

from .models import EncounterStateResponse, ResumeRequest, StartEncounterRequest
from .store import EncounterStore


def _serialize(res) -> dict:
    return {
        "encounter_id": res.encounter_id,
        "status": res.status,
        "awaiting_domain": res.awaiting_domain,
        "awaiting_gate": res.awaiting_gate.model_dump() if res.awaiting_gate else None,
        "summary": res.summary,
        "domains": {k: v["status"] for k, v in res.domains.items()},
    }


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    app = FastAPI(title="Healthcare Agentic AI", version="0.1.0",
                  description="Production-grade multi-agent healthcare encounter pipeline.")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    registry = build_registry(settings)
    master = MasterOrchestrator(registry, LLMClient(settings))
    store = EncounterStore()

    @app.get("/", response_class=HTMLResponse)
    def ui() -> HTMLResponse:
        try:
            with open(_WEB_INDEX, encoding="utf-8") as fh:
                html = fh.read()
        except FileNotFoundError:
            html = "<h1>Demo UI not found (web/index.html)</h1>"
        # Never cache the demo page, so UI edits always show on reload.
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    _domains = [master.scheduling, master.patient, master.clinical, master.checkout,
                master.insurance, master.reconciliation, master.pharmacy, master.fraud]
    _agent_count = sum(len(d.steps) for d in _domains)   # computed, not hand-maintained — see gate.py

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "provider": settings.llm_provider,
                "agents": _agent_count, "domains": len(_domains)}

    @app.post("/encounters", response_model=EncounterStateResponse)
    async def start_encounter(body: StartEncounterRequest) -> dict:
        eid = store.create(body.model_dump())
        master.llm.call_log.clear()
        res = await master.execute_encounter(store.get(eid))
        out = _serialize(res)
        out["llm_calls"] = list(master.llm.call_log)
        return out

    @app.post("/encounters/{eid}/resume", response_model=EncounterStateResponse)
    async def resume_encounter(eid: str, body: ResumeRequest) -> dict:
        if store.get(eid) is None:
            raise HTTPException(status_code=404, detail="encounter not found")
        store.add_decision(eid, body.gate_id,
                           {"approved": body.approved, "actor": body.actor, "note": body.note})
        master.llm.call_log.clear()
        res = await master.execute_encounter(store.get(eid))
        out = _serialize(res)
        out["llm_calls"] = list(master.llm.call_log)
        return out

    @app.get("/encounters/{eid}", response_model=EncounterStateResponse)
    async def get_encounter(eid: str) -> dict:
        req = store.get(eid)
        if req is None:
            raise HTTPException(status_code=404, detail="encounter not found")
        res = await master.execute_encounter(req)
        return _serialize(res)

    @app.get("/encounters/{eid}/status")
    async def get_status(eid: str) -> dict:
        req = store.get(eid)
        if req is None:
            raise HTTPException(status_code=404, detail="encounter not found")
        res = await master.execute_encounter(req)
        return {"encounter_id": eid, "status": res.status,
                "awaiting_gate": res.awaiting_gate.gate_id if res.awaiting_gate else None}

    return app


app = create_app()
