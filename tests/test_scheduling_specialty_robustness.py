"""
Regression suite: a real LLM emits open-vocabulary specialties.

The sandbox provider returns a fixed heuristic parse, so the offline test suite can
only ever produce General Dentistry / Orthodontics / Oral & Maxillofacial Surgery.
That hid a live bug: against a real provider the parser returned specialties like
"Periodontics" or "Endodontics", ProviderMatcher hard-failed, and because scheduling
aborts on failure the ENTIRE encounter died. Most chief complaints could not be booked
at all.

These tests stub the LLM so the adversarial responses a real model produces are
exercised offline — no keys, no network.
"""
from __future__ import annotations

import json

import pytest

from src.agents.scheduling import SchedulerOrchestrator
from src.agents.scheduling.request_parser import RequestParser
from src.config import Settings
from src.core.llm.types import LLMResponse, TokenUsage
from src.core.orchestrator import GateDecision, PipelineContext
from src.integrations import build_registry
from src.shared.enums import PipelineStatus


class StubLLM:
    """Returns a canned payload for every call, mimicking a real provider."""

    def __init__(self, content: str):
        self.content = content
        self.call_log: list[dict] = []

    async def complete(self, request) -> LLMResponse:
        self.call_log.append({"agent": request.agent_name, "provider": "stub"})
        return LLMResponse(content=self.content, provider="stub", model="stub-1",
                           usage=TokenUsage())

    async def call(self, request) -> LLMResponse:
        return await self.complete(request)


def _registry():
    return build_registry(Settings(_env_file=None))


def _spec(specialty: str) -> str:
    return json.dumps({"specialty": specialty, "reason": "r", "preferred_provider_name": ""})


# Specialties a real model actually returned, none of which the directory staffs.
OUT_OF_VOCAB = [
    "Periodontics",
    "Endodontics",
    "Prosthodontics",
    "Pediatric Dentistry",
    "Dental Sleep Medicine",
    "Cosmetic Dentistry",
    "Dental Anesthesiology",
    "Public Health Dentistry",
    "General Practice",
]


@pytest.mark.parametrize("specialty", OUT_OF_VOCAB)
async def test_out_of_vocabulary_specialty_is_snapped_to_a_staffed_one(specialty):
    reg = _registry()
    parser = RequestParser(StubLLM(_spec(specialty)), reg)
    ctx = PipelineContext(encounter_id="R1", input_data={"request_text": "whatever"})

    res = await parser.execute(ctx)

    assert res.status == "completed"
    allowed = await reg.directory.specialties()
    assert res.output["specialty"] in allowed, \
        f"{specialty!r} snapped to {res.output['specialty']!r}, not in {allowed}"
    # the original is preserved for audit rather than silently discarded
    assert res.output["requested_specialty"] == specialty
    # and the specialty we hand downstream is actually bookable
    assert await reg.directory.find(res.output["specialty"])


MALFORMED = [
    pytest.param("not json at all", id="plain-text"),
    pytest.param("", id="empty-string"),
    pytest.param("[]", id="json-array"),
    pytest.param("null", id="json-null"),
    pytest.param('{"specialty": null}', id="null-specialty"),
    pytest.param('{"specialty": ""}', id="empty-specialty"),
    pytest.param('{"reason": "no specialty key"}', id="missing-key"),
    pytest.param('```json\n{"specialty": "Periodontics"}\n```', id="fenced-markdown"),
]


@pytest.mark.parametrize("content", MALFORMED)
async def test_malformed_llm_output_still_yields_a_bookable_specialty(content):
    reg = _registry()
    parser = RequestParser(StubLLM(content), reg)
    ctx = PipelineContext(encounter_id="R2", input_data={"request_text": "bad cough"})

    res = await parser.execute(ctx)

    assert res.status == "completed"
    assert res.output["specialty"] in await reg.directory.specialties()
    assert await reg.directory.find(res.output["specialty"])


@pytest.mark.parametrize("specialty", ["Periodontics", "Endodontics", "Prosthodontics"])
async def test_full_scheduling_domain_survives_out_of_vocabulary_specialty(specialty):
    """The end-to-end guarantee: scheduling never aborts on an odd specialty."""
    reg = _registry()
    orch = SchedulerOrchestrator(registry=reg, llm_client=StubLLM(_spec(specialty)))

    paused = await orch.run(PipelineContext(
        encounter_id="R3", input_data={"patient_id": "PAT-001",
                                       "request_text": "something unusual"}))
    assert paused.status == PipelineStatus.AWAITING_HUMAN, paused.errors
    assert paused.gate.gate_id == "scheduling.slot_selection"

    ctx = PipelineContext(encounter_id="R3", input_data={"patient_id": "PAT-001",
                                                        "request_text": "something unusual"})
    ctx.add_decision(GateDecision(gate_id="scheduling.slot_selection", approved=True,
                                  actor="Patient", note="0"))
    done = await orch.run(ctx)
    assert done.status == PipelineStatus.COMPLETED, done.errors
    assert done.output["appointment"]["status"] == "booked"


async def test_directory_without_specialties_method_does_not_break_parser():
    """Adapter swap safety: a vendor directory lacking specialties() still works."""

    class LegacyDirectory:
        async def find(self, specialty, accepting_new=True):
            return []

        async def get(self, npi):
            return None

    class Reg:
        directory = LegacyDirectory()

    parser = RequestParser(StubLLM(_spec("Periodontics")), Reg())
    res = await parser.execute(PipelineContext(encounter_id="R4", input_data={}))
    assert res.status == "completed"
    assert res.output["specialty"] == "General Dentistry"


async def test_matcher_reports_the_downgrade_it_made():
    """A silent downgrade would be a clinical-safety problem — it must be visible."""
    from src.agents.scheduling.provider_matcher import ProviderMatcher

    reg = _registry()
    ctx = PipelineContext(encounter_id="R5", input_data={})
    # Simulate a parser that let an unstaffed specialty through anyway.
    ctx.add_result("request_parser", {"specialty": "Orthopedics"})

    res = await ProviderMatcher(reg).execute(ctx)

    assert res.status == "completed"
    assert res.output["requested_specialty"] == "Orthopedics"
    assert res.output["matched_specialty"] != "Orthopedics"
    assert res.output["fallback_reason"], "downgrade must be explained, not silent"


async def test_unknown_preferred_npi_falls_back_by_specialty():
    from src.agents.scheduling.provider_matcher import ProviderMatcher

    reg = _registry()
    ctx = PipelineContext(encounter_id="R6",
                          input_data={"preferred_provider_npi": "0000000000"})
    ctx.add_result("request_parser", {"specialty": "General Dentistry"})

    res = await ProviderMatcher(reg).execute(ctx)
    assert res.status == "completed"
    assert "not in directory" in res.output["fallback_reason"]
    assert res.output["selected_npi"]
