# Healthcare Agentic AI — Production-Grade Multi-Agent Platform (Dental Practice)

> **Want to deploy this as a live, shareable website?** See [DEPLOY.md](DEPLOY.md) —
> free-tier hosting, no API key required for the public demo, and a clear
> explanation of how the optional live-AI mode handles secrets safely.

An end-to-end, standards-shaped dental-practice encounter pipeline built as **76
single-task agents** (82 pipeline-step executions per full encounter, since the
shared audit logger runs once per domain) across **8 domains**, coordinated by domain
orchestrators and one master orchestrator, with **17 human touchpoints** wired as
real pause/resume gates.

The domain order follows how a US dental practice actually works, which is not the
intuitive order — see [docs/us-dental-clinic-real-world-workflow.md](docs/us-dental-clinic-real-world-workflow.md).
Insurance is verified **pre-visit**, because that is what makes the treatment estimate
accurate. The patient then pays an **estimate at checkout**, on the day of service,
*before* any claim is filed — there is no approval gate between treatment and
collecting money. The claim goes out afterwards, the payer's 835 ERA arrives 1–2 weeks
later, and only then is the estimate **reconciled** into a balance statement or a
refund. That is why billing is two domains rather than one.

The clinical path is a real diagnose-then-treatment-plan flow — a dentist reviews an
AI-drafted, multi-procedure treatment plan (tooth, CDT code, phase, fee) before a
patient consents to specific line items — and the insurance path models both halves of
"the clinic requests payment": claim submission and the payer's actual remittance
response (paid amount, contractual write-off, and CARC adjustment reason codes).

## The documentation → claim chain

The dentist's artifact is a **signed chart note**, not a code picked from a dropdown —
that is how dental charting actually works, and the note is the legal record. The AI
reads what they signed:

```
diagnosis_signoff        GATE   dentist edits a dictated chart note and signs it
clinical_note_transcriber  AI   prose → per-tooth diagnoses + measurable findings
  ↓ treatment plan → dentist review → patient consent → procedures performed
diagnosis_coder                 ICD-10 per line + ADA item 29a pointers
claim_narrative_writer     AI   per-tooth narrative the payer's consultant reads
```

Two details that make this dental rather than medical:

- **Diagnosis is per procedure line, not per encounter.** The 2024 ADA claim form
  carries up to four diagnosis codes (item 34a) with a per-line **Diagnosis Code
  Pointer** (item 29a). One encounter-level code can't express an ordinary
  two-problem visit.
- **The narrative is the high-value output, not the code.** CDT is a closed vocabulary
  the dentist already knows; the narrative is free text that decides whether the claim
  gets paid, and inadequate narratives are the leading cause of dental denials. Each
  one names the tooth, the measurable findings, the imaging, and why a cheaper
  alternative wouldn't suffice.

Diagnosis codes are computed always and *submitted* conditionally: Medicare rejects
dental claims without a valid ICD-10 (eff. 2025-07-01) and several state Medicaid
programs require one, while most commercial dental plans adjudicate on CDT alone.

Everything runs **offline** on high-fidelity sandbox services (real code systems,
valid identifiers, real drug-interaction data), and every external service sits behind
an adapter so it can be swapped for a live vendor with no agent-code changes. One EHR
read can hit a real public FHIR server for a genuine live-integration moment.

> Demo framing: this runs on standards-compliant **simulated** services (FHIR R4, X12
> EDI/837D, CDT, NCPDP, EPCS, PDMP). Going live requires vendor credentials/certifications
> (Surescripts, DEA EPCS, a dental PMS such as Dentrix/Eaglesoft/Open Dental, a
> healthcare payment processor).

## Architecture

```
MasterOrchestrator                                        (src/core/pipeline)

  PRE-VISIT    Scheduling      book + verify eligibility (X12 270/271)
  VISIT DAY    Patient         check-in, identity, consent, history
               Clinical        diagnose → plan → consent → treat → transmit Rx
               Checkout        ESTIMATE the patient's share and COLLECT it
  POST-VISIT   Insurance       file the claim (837D) → payer's remittance (835 ERA)
               Reconciliation  settle estimate vs actual → balance bill or refund
               Pharmacy        the pharmacy's own async workflow
               + Fraud Detection    (parallel observer, never blocks)
               + Recall Scheduler   (post-visit, deterministic — see below)

  └─ 8 DomainOrchestrators                                (src/agents/*/orchestrator.py)
       └─ 76 single-task Agents                           (one file, one responsibility each)
  behind adapter ports → sandbox / real                   (src/integrations)
```

Two orderings here are deliberate corrections, not arbitrary:

- **Eligibility is verified in Scheduling, not at check-in.** A coverage check that
  happens once the patient is in the chair is too late to price the visit.
- **Checkout runs before Insurance.** The patient pays an estimate on the day of
  service; the payer has not adjudicated anything and will not for 1–2 weeks. Running
  Insurance first would imply the office knows the payer's answer when it bills the
  patient, which inverts the most consequential sequence in dental revenue cycle.

`recall_scheduler` (Scheduling domain) isn't a step inside `SchedulerOrchestrator` —
real recall/recare systems only make sense once the visit's actual procedures are
known, which is only true after Clinical has run, so the master orchestrator invokes
it directly once the encounter completes. See its docstring for the full reasoning.

Automation split: **47 fully automatable · 12 partially automatable · 17 human gates**
(ceiling ≈ 85% if an org accepts the risk on the 6 policy/judgment gates; **7 of the
17 are floor-mandated by law**, not a design choice).

Human gates (pause/resume): scheduling referral, patient MPI conflict, patient consent,
clinical critical-value, diagnosis sign-off, **dentist treatment-plan review**,
**patient treatment consent**, controlled-Rx EPCS signing, insurance predetermination
review, coding QA, **patient payment authorization (of the estimate, at checkout)**,
**claim rejection (277CA, correct-and-resubmit)**, **document request (277RFAI, only for
records the AI can't find)**, denial/appeal (post-ERA), pharmacist verification, and
fraud SIU review (non-blocking).

## When the payer wants more evidence

A claim can come back three ways, not two. The middle one is the common one and it is
**not a denial** — the payer is asking, not refusing:

```
CLINIC                                        PAYER
 │── 837D claim ──────────────────────────►    syntax + front-end edits
 │◄─ 277CA accepted ───────────────────────    into adjudication
 │                                             eligibility on date of service ✓
 │                                             benefit / frequency lookup ✓
 │                                             documentation check ✗
 │◄─ 277RFAI  2 documents ─────────────────    PENDED · 30-day clock
 │  🤖 both films already on file
 │── 275 attachment + PWK ────────────────►    adjudication resumed
 │                                             consultant reviews narrative + imaging ✓
 │◄─ 835 ERA  paid ────────────────────────    CARC 45 / 3 / 1 / 2
```

The whole exchange is visible in the demo UI, with payer-side rows marked **simulated
payer-side adjudication** — a practice never sees inside adjudication, so those rows are a
reconstruction from the transactions the payer returns plus published plan rules, not data
any payer discloses.

The routing is the point. `information_request_router` asks one question per requested
document — *is this already in the record?* — because that, not the document's type, is
what decides whether a human gets involved:

| Payer asks for | Already exists? | Resolved by |
|---|---|---|
| Pre-op radiograph taken during the procedure | yes | **AI** — attach, nobody asked |
| Narrative, chart note, treatment plan | yes | **AI** |
| Perio charting already recorded | yes | **AI** |
| A film that was never taken | no | dentist — **patient must return** |
| Perio charting never done | no | hygienist — patient must return |
| Physician letter of medical necessity | no, and external | admin — days to weeks |

Most requests are answerable from documents the practice already holds; the film exists, it
just never got attached. `imaging_recorder` logs what each procedure actually captured, so
"already on file" is a fact about a real artifact rather than an assumption. Only the
remainder opens the `insurance.document_request` gate, and ignoring that gate lets the
30-day clock convert the pend into a missing-information denial.

`attachment_assembler` will not emit a **PWK segment without a payload** — a declared but
absent attachment strands a claim indefinitely at some payers, which is worse than sending
nothing at all.

## When the claim fails — two different things

Rejection and denial get conflated constantly and need opposite work. The pipeline
branches them on purpose:

| | **Rejected** | **Denied** |
|---|---|---|
| When | Front-end edits, before adjudication | After adjudication |
| Transaction | **277CA** | **835 ERA** |
| Reason data | Status codes + the offending data element | **CARC/RARC** |
| Appealable? | **No** — the payer never saw it | Yes |
| Fix | Correct the field, resubmit as a replacement (frequency code 7) | Appeal, ~30–90 days |
| Gate | `insurance.claim_rejection` | `billing.denial` |

A rejected claim **skips the remittance entirely** — an 835 for a claim that never
entered adjudication cannot happen, and reconciling against one would settle the
patient's balance against a fiction. The balance stays unresolved in AR instead.

Denials are classified rather than lumped, because eight reasons route to five actions
and **only two are appeals** (see [payer_outcomes.py](src/shared/payer_outcomes.py)):
a missing attachment is a *resubmission*; a frequency cap or exhausted annual maximum is
the *patient's bill*; untimely filing is a *write-off* the patient cannot be billed for;
and a LEAT downgrade is a **paid** claim whose differential the patient owes, not a
denial at all.

## Quick start

```powershell
# from the project root
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# run the tests (offline, deterministic)
python -m pytest -q

# start the API + demo UI
uvicorn src.api.app:app --reload --port 8000
```

Then open:
- **http://localhost:8000/** — the live demo UI (start an encounter, approve each human gate)
- **http://localhost:8000/docs** — Swagger API explorer

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/encounters` | start an encounter (runs to the first human gate) |
| POST | `/encounters/{id}/resume` | supply a decision for a gate, then continue |
| GET | `/encounters/{id}` | current encounter state + summary |
| GET | `/encounters/{id}/status` | lightweight status |
| GET | `/health` | health check |

## Configuration (`.env`, copy from `.env.example`)

- `LLM_PROVIDER` = `sandbox` (default, offline) | `groq` | `gemini` | `anthropic` (+ that provider's API key)
- `EHR_MODE` = `sandbox` | `fhir_public` (real public FHIR read) + `FHIR_PUBLIC_BASE_URL`
- `SELF_PAY_DISCOUNT_PCT` = provider-configurable self-pay discount (default `0.0`)

## Demo data (optional Synthea)

The sandbox ships with built-in demo patients (valid ICD-10 / CDT / RxNorm / NPI). For richer,
clinically-coherent records you can seed from **Synthea**:

```bash
java -jar synthea-with-dependencies.jar -p 25 --exporter.fhir.export true
# copy output/fhir/*.json into data/synthea/output/fhir/
```

`src/integrations/synthea.py` loads them automatically; if absent, the built-in patients
are used, so the demo works either way.

## Layout

```
src/
  config.py, logging_setup.py
  core/llm/           provider-agnostic LLM client (sandbox/groq/gemini/anthropic)
  core/orchestrator/  Agent, HumanGateAgent, DomainOrchestrator, pause/resume gate
  core/pipeline/      MasterOrchestrator + EncounterResult
  integrations/       adapter ports + sandbox/real impls + ServiceRegistry + seed data
  agents/             scheduling, patient, clinical, insurance, billing, pharmacy, fraud
                      (billing holds BOTH phases: CheckoutOrchestrator and
                       ReconciliationOrchestrator — see agents/billing/__init__.py)
  api/                FastAPI app, models, in-memory encounter store
  shared/             code validators, cost-share math, and the clinical text
                      (draft chart notes + claim-narrative templates) in dental_text.py
web/index.html        zero-build demo UI (served at /), grouped by pre/visit/post phase
docs/                 real-world workflow research + sandbox/deductible references
tests/                full test suite (195 tests)
```
