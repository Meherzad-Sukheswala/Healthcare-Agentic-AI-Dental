"""
Treatment Cost Estimator (single task: chairside cost estimate for the plan). FULL.

Applies the patient's actual benefit structure (category coverage %, remaining
annual maximum) to each treatment-plan line item, the way a treatment coordinator
would before presenting the plan for financial consent. This is an ESTIMATE using
benefits data already on file — the real, final number comes later from the payer's
actual remittance (insurance/remittance_processor.py) once the claim is adjudicated;
the two are expected to differ occasionally, same as in real practice.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

# CDT -> dental benefit category (preventive/basic/major is how real plans structure coverage)
_CATEGORY = {
    "D0120": "preventive", "D0140": "preventive", "D0150": "preventive",
    "D0210": "preventive", "D0274": "preventive",
    "D1110": "preventive", "D1120": "preventive", "D1206": "preventive", "D1208": "preventive",
    "D2140": "basic", "D2150": "basic", "D2391": "basic", "D2392": "basic",
    "D3310": "basic", "D3330": "basic", "D4341": "basic", "D4342": "basic",
    "D7880": "basic", "D7140": "basic",
    "D2740": "major", "D2750": "major", "D2790": "major", "D2950": "major",
    "D6010": "major", "D6058": "major", "D6059": "major",
    "D7953": "major", "D8080": "major", "D4260": "major",
}


def _category(cdt: str) -> str:
    return _CATEGORY.get(cdt, "basic")


class TreatmentCostEstimator(Agent):
    name = "treatment_cost_estimator"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        plan = ctx.get_result("treatment_plan_builder")
        items = plan.get("items", [])
        coverage = ctx.input_data.get("coverage", {}) or {}
        pct_by_category = coverage.get("category_coverage_pct", {}) or {}
        max_cents = int(coverage.get("annual_max_cents", 0))
        used_cents = int(coverage.get("annual_max_used_cents", 0))
        remaining_max = max(0, max_cents - used_cents) if coverage.get("active") else 0

        estimates = []
        insurer_total = 0
        for item in items:
            category = _category(item["cdt"])
            pct = float(pct_by_category.get(category, 0.5)) if coverage.get("active") else 0.0
            insurer_share = min(round(item["fee_cents"] * pct), remaining_max - insurer_total)
            insurer_share = max(0, insurer_share)
            patient_share = item["fee_cents"] - insurer_share
            estimates.append({
                "item_id": item["item_id"], "cdt": item["cdt"], "category": category,
                "fee_cents": item["fee_cents"], "coverage_pct": pct,
                "estimated_insurer_cents": insurer_share, "estimated_patient_cents": patient_share,
            })
            insurer_total += insurer_share

        total_fee = sum(i["fee_cents"] for i in items)
        return AgentResult.completed({
            "estimates": estimates,
            "total_fee_cents": total_fee,
            "estimated_insurer_cents": insurer_total,
            "estimated_patient_cents": total_fee - insurer_total,
            "annual_max_remaining_cents": remaining_max,
        })
