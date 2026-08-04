"""
Imaging Recorder (single task: log the radiographs actually taken this visit). FULL.

WHY THIS AGENT EXISTS
---------------------
Because the most valuable thing the claim-documentation path does is answer "do we
already have the film the payer is asking for?" — and that answer has to be real. Without
a record of what imaging was genuinely captured, the AI attaching a radiograph is a
hand-wave: it would be claiming to attach a file nobody ever took.

Dental imaging is procedure-driven and predictable, which is what makes this modellable.
A dentist does not decide what to shoot arbitrarily:

  endodontics      pre-op periapical, working films, post-op periapical
  crown / buildup  pre-op periapical of the tooth
  perio (SRP)      full-mouth series or bitewings, plus periodontal charting
  implant / graft   CBCT
  hygiene recall   bitewings (typically four films, D0274)
  problem-focused  periapical of the area of complaint

Each image is recorded against its tooth or region, the way a real imaging system stores
it, so an attachment can reference a specific film rather than "a radiograph".

`imaging_omitted` on the request models the real failure that drives most documentation
requests: the procedure was done but the film was never captured, or was captured and
never linked to the claim. That is the case where a human has to act, and where the
patient may have to come back in.
"""
from __future__ import annotations

from src.core.orchestrator import Agent, AgentResult
from src.shared.enums import Automation

# CDT prefix/code -> the images a real visit captures for it.
# (doc_key, label template) — {tooth} is substituted with the universal tooth number.
_IMAGING_PROTOCOL: dict[str, list[tuple[str, str]]] = {
    "D3310": [("preop_radiograph", "PA #{tooth} pre-op"), ("postop_radiograph", "PA #{tooth} post-op")],
    "D3320": [("preop_radiograph", "PA #{tooth} pre-op"), ("postop_radiograph", "PA #{tooth} post-op")],
    "D3330": [("preop_radiograph", "PA #{tooth} pre-op"), ("postop_radiograph", "PA #{tooth} post-op")],
    "D2740": [("preop_radiograph", "PA #{tooth} pre-op")],
    "D2750": [("preop_radiograph", "PA #{tooth} pre-op")],
    "D2790": [("preop_radiograph", "PA #{tooth} pre-op")],
    "D2950": [("preop_radiograph", "PA #{tooth} pre-op")],
    "D2391": [("bitewings", "BW #{tooth} pre-op")],
    "D2392": [("bitewings", "BW #{tooth} pre-op")],
    "D4341": [("full_mouth_series", "Full-mouth series, 18 films")],
    "D4342": [("bitewings", "Vertical bitewings")],
    "D6010": [("cbct", "CBCT mandible, site #{tooth}")],
    "D7953": [("cbct", "CBCT mandible, site #{tooth}")],
    "D6058": [("preop_radiograph", "PA #{tooth} — osseointegration check")],
    "D1110": [("bitewings", "BW x4")],
    "D0120": [("bitewings", "BW x4")],
    "D0140": [("preop_radiograph", "PA of the area of complaint")],
    "D0150": [("full_mouth_series", "Full-mouth series, 18 films")],
}

# Procedures whose documentation includes periodontal charting rather than imaging.
_PERIO_CHARTED = {"D4341", "D4342", "D4910", "D1110", "D0120", "D0150"}


class ImagingRecorder(Agent):
    name = "imaging_recorder"
    automation = Automation.FULL

    async def execute(self, ctx) -> AgentResult:
        performed = ctx.get_result("procedure_documentor").get("performed_items", [])
        # Demo hook: the film was never captured (or never linked), which is what puts a
        # human on the critical path when the payer asks for it.
        omitted = {str(k) for k in (ctx.input_data.get("imaging_omitted") or [])}

        images: dict[str, list[str]] = {}
        skipped: list[dict] = []
        for item in performed:
            cdt = str(item.get("cdt", "")).upper()
            tooth = item.get("tooth", "") or "—"
            for doc_key, template in _IMAGING_PROTOCOL.get(cdt, []):
                label = template.format(tooth=tooth)
                if doc_key in omitted:
                    skipped.append({"doc_key": doc_key, "label": label, "cdt": cdt})
                    continue
                images.setdefault(doc_key, [])
                if label not in images[doc_key]:
                    images[doc_key].append(label)

        codes = {str(i.get("cdt", "")).upper() for i in performed}
        # Periodontal charting is recorded when a perio/hygiene procedure was performed
        # AND the dentist's note actually carries probing depths — the note is the proof.
        note_findings = ctx.get_result("clinical_note_transcriber").get("findings", {})
        has_depths = "probing_depths" in (note_findings.get("measurements") or {})
        perio_charted = bool(codes & _PERIO_CHARTED) and has_depths and "perio_charting" not in omitted

        return AgentResult.completed({
            "images": images,
            "image_count": sum(len(v) for v in images.values()),
            "perio_charted": perio_charted,
            # what a payer may later ask for that this visit did NOT capture
            "not_captured": skipped,
        })
