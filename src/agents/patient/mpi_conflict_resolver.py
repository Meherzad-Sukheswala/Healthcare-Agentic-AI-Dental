"""
MPI Conflict Resolver (single task: human resolves an ambiguous identity). MANUAL.

Runs only when the identity matcher flagged ambiguity. An MPI steward confirms the
correct master-patient record before any clinical data is attached.
"""
from __future__ import annotations

from src.core.orchestrator import GateRequest, HumanGateAgent


class MPIConflictResolver(HumanGateAgent):
    name = "mpi_conflict_resolver"
    gate_id = "patient.mpi"

    def build_request(self, ctx) -> GateRequest:
        idm = ctx.get_result("identity_matcher")
        return GateRequest(
            gate_id=self.gate_id,
            title="MPI identity conflict",
            prompt="Confirm the correct master-patient record for this encounter.",
            domain="patient",
            data={"candidate_mpi_id": idm.get("mpi_id", ""), "match_score": idm.get("match_score")},
        )

    def on_approved(self, ctx, decision) -> dict:
        return {"mpi_resolved": True, "mpi_id": ctx.get_result("identity_matcher").get("mpi_id", ""),
                "resolved_by": decision.actor}
