"""
Information Request Router (single task: decide who answers each requested document). PARTIAL.

THE AGENT WITH THE ACTUAL VALUE IN IT
-------------------------------------
When a payer pends a claim for documentation, the practice's real question is not "what
do they want" — the 277RFAI says that. It is "can we answer this from what we already
have, or does somebody have to go and make something?"

Most of the time the answer is the former. The radiograph exists; it was taken during the
procedure and simply never got attached to the claim. That case needs no human at all.
The expensive case is the artifact that does not exist yet, because producing it can mean
the patient comes back in, or another office has to be chased for weeks.

So this agent splits the request in two:

  auto_satisfiable   the document is in the record -> attachment_assembler sends it
  escalated          it is not -> a NAMED human is asked, via the document_request gate

and for each escalated item it says who (dentist / hygienist / admin) and whether the
patient has to return, because "we need a pre-op film of a tooth we already root-canalled"
is a fundamentally worse problem than "we need the referral form from the GP".

The decision itself lives in shared/document_registry.resolve() so this agent and the gate
cannot disagree about what is available.

Why PARTIAL rather than FULL: the routing is deterministic, but its output determines
whether a human is asked, and the escalated half is reviewed at a gate.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.document_registry import BY_AI, resolve
from src.shared.enums import Automation


class InformationRequestRouter(Agent):
    name = "information_request_router"
    automation = Automation.PARTIAL

    async def execute(self, ctx) -> AgentResult:
        requested = ctx.get_result("information_request_receiver").get("requested", [])
        registry = ctx.input_data.get("document_registry", {}) or {}

        auto, escalated = [], []
        for item in requested:
            decision = resolve(item.get("doc_key", ""), registry)
            decision["reason"] = item.get("reason", "")
            decision["service_line_cdt"] = item.get("service_line_cdt", "")
            (auto if decision["resolved_by"] == BY_AI else escalated).append(decision)

        # Who is being asked, and the worst-case cost of asking them.
        actors = sorted({e["resolved_by"] for e in escalated})
        needs_visit = any(e["needs_patient_visit"] for e in escalated)

        return AgentResult.completed({
            "auto_satisfiable": auto,
            "escalated": escalated,
            "auto_count": len(auto),
            "escalated_count": len(escalated),
            # True when the AI can answer the payer with nobody in the practice touching it
            "fully_automated": bool(requested) and not escalated,
            "needs_human": bool(escalated),
            "actors_required": actors,
            "patient_must_return": needs_visit,
            "summary": _summarise(len(auto), escalated, needs_visit),
        })


def _summarise(auto_count: int, escalated: list[dict], needs_visit: bool) -> str:
    if not escalated:
        return (f"All {auto_count} requested document(s) are already in the record — "
                "attaching and resubmitting with no staff involvement.")
    who = ", ".join(sorted({e["resolved_by"] for e in escalated}))
    tail = " The patient has to come back in for it." if needs_visit else ""
    return (f"{auto_count} of {auto_count + len(escalated)} document(s) already on file. "
            f"{len(escalated)} must be produced by: {who}.{tail}")
