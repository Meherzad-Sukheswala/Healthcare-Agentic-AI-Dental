# Impact Model — Benchmark-Based Projected Impact
**Healthcare Agentic AI (Production Grade build, dental practice) · Modeled practice: a 10-dentist group practice, ~40,000 encounters/year**
Prepared 2026-07-18, updated 2026-08-02 for the dental re-skin. Every figure below traces to either (a) this codebase (file path given) or (b) a published source (link given). Modeling assumptions are explicitly labeled `ASSUMPTION`.

> **Honesty note:** These are *projected* impact figures from a benchmark model, not measured results from a deployment. Say "modeled on published benchmarks" in interviews, never "achieved."

> **Dental cross-application caveat (volunteer this):** S1 (AMA) is a *physician* survey and S2/S3 (CAQH Index) report *medical* per-transaction benchmarks — neither is a dental-specific sample. The figures below assume administrative-burden mechanics (staff minutes per prior-auth, eligibility check, claim submission, etc.) are comparable between medical and dental revenue-cycle operations, which is directionally reasonable — the same X12 270/271/278/837 transaction types and clearinghouse workflows underlie both — but is an unvalidated cross-application, not a dental-sourced figure. If pressed: "I didn't have a clean dental-specific administrative-burden study, so I cross-applied medical RCM benchmarks and labeled it as an assumption rather than overstate precision."

---

## 1. Sources

| # | Source | Figure(s) used | Link |
|---|--------|----------------|------|
| S1 | AMA 2024 Prior Authorization Physician Survey (Dec 2024, n=1,000) | 13 hrs/week of physician+staff time on PA per physician; ~40 PAs/physician/week; 40% of physicians employ PA-dedicated staff | https://fixpriorauth.org/2024-ama-prior-authorization-physician-survey and https://www.ama-assn.org/practice-management/prior-authorization/fixing-prior-auth-nearly-40-prior-authorizations-week-way |
| S2 | CAQH Index 2024 (full report) | Manual PA = 24 min, portal PA = 16 min; provider time-savings opportunity per transaction (manual→electronic): PA 14 min, eligibility 12 min, claim submission 7 min, claim status inquiry 18 min, remittance advice 4 min, claim payment 3 min; medical claim-submission electronic adoption 98%; ERA adoption 89% | https://www.caqh.org/hubfs/Index/2024%20Index%20Report/CAQH_IndexReport_2024_FINAL.pdf |
| S3 | CAQH Index 2024 Key Takeaways | Up to 70 min/visit total savings from fully electronic workflows; $20B industry opportunity | https://www.caqh.org/hubfs/Index/2024%20Index%20Report/CAQH%202024%20Index%20Report%20Key%20Takeaways%20FINAL.pdf |
| S4 | Experian Health, State of Claims 2024/2025 | Top denial causes: missing/inaccurate claim data (~46–50%), prior authorization issues (35%), registration/intake data (32%); ~4 in 10 providers report >10% of claims denied | https://www.experian.com/blogs/healthcare/healthcare-claim-denials-statistics-state-of-claims-report/ and https://www.healthcaredive.com/news/provider-claims-denials-increase-2024-experian-health-study/727999/ |
| S5 | Industry denial-rate roundups (Experian/Premier data) | Initial claim denial rate ~10–12% (11.8% reported for 2024) | https://www.aptarro.com/insights/us-healthcare-denial-rates-reimbursement-statistics |
| S6 | Premier Inc. denial-cost research | Admin cost to rework/appeal a denied claim: $43.84 (2022) → $57.23 (2023) | https://www.techtarget.com/revcyclemanagement/feature/Breaking-down-claim-denial-rates-by-healthcare-payer |
| S7 | MGMA / Advisory Board | ~86–90% of denials are potentially preventable | https://www.mgma.com/mgma-stats/6-keys-to-addressing-denials-in-your-medical-practice-s-revenue-cycle |
| S8 | BLS OES, Medical Records Specialists (29-2072), May 2024 | Mean wage ≈ $26.91/hr ($55,970/yr) | https://www.bls.gov/oes/2024/may/featured_data.htm (occupation page: https://www.bls.gov/ooh/healthcare/medical-records-and-health-information-technicians.htm) |
| S9 | BLS Employer Costs for Employee Compensation (Mar 2025) | Wages = 70.3% of total compensation (private industry) → loaded-cost multiplier ≈ 1.42 | https://www.bls.gov/news.release/archives/ecec_06132025.htm |
| S10 | Groq published pricing | Llama-3.3-70B: $0.59 / $0.79 per 1M input/output tokens | https://groq.com/pricing |
| S11 | Anthropic published pricing | Claude Sonnet 4.5: $3.00 / $15.00 per 1M input/output tokens | https://platform.claude.com/docs/en/about-claude/pricing |
| S12 | Google published pricing | Gemini 2.5 Flash: $0.15 / $1.25 per 1M input/output tokens | https://ai.google.dev/gemini-api/docs/pricing |

---

## 2. Scope: what this system actually automates

Only burden handled by an agent in this codebase is counted. Mapping of benchmark category → domain orchestrator (all paths under `src/agents/`):

| Benchmark category | Handled by (verified in code) |
|---|---|
| Predetermination submission & tracking | `insurance/predetermination_submitter.py` (FULL), `insurance/predetermination_review.py` (human gate — payer clinician decision stays human) |
| Eligibility & benefit verification | `patient/eligibility_verifier.py` (FULL, now wired PRE-VISIT into the scheduling domain), `insurance/eligibility_checker.py` (FULL, claim-time date-of-service re-check), `insurance/formulary_checker.py` (FULL) |
| Claim build & submission | `insurance/claim_builder.py`, `insurance/claim_submitter.py` (FULL, ADA Dental Claim / X12 837D, multi-line, with per-line diagnosis pointers and narratives); coding via `clinical/clinical_note_transcriber.py` (PARTIAL, LLM — the dentist's signed note into per-tooth diagnoses) + `clinical/diagnosis_coder.py` (PARTIAL, ICD-10 per line + ADA item 29a pointers) + `clinical/claim_narrative_writer.py` (PARTIAL, LLM — the per-tooth justification a payer's consultant reads) + `clinical/treatment_plan_builder.py` (PARTIAL, drafts the procedures) + `clinical/procedure_documentor.py` (FULL, records what was actually billable) + `billing/charge_coding_qa.py` (gate, pre-submission at checkout) |
| Claim rejection (pre-adjudication) | `shared/claim_scrubber.py` (front-end 277CA edits — subscriber ID, NPI check digit, tooth number on tooth-specific CDT, payer-required diagnosis), `insurance/claim_rejection_handler.py` (gate — correct and resubmit as a replacement, frequency code 7). Distinct from denial: no CARC codes exist and there is nothing to appeal |
| Documentation requests (277RFAI → 275) | `insurance/information_request_receiver.py` (FULL, reads the payer's pend), `insurance/information_request_router.py` (PARTIAL — decides per document whether the record can answer it), `shared/document_registry.py` + `clinical/imaging_recorder.py` (FULL, what the visit actually captured), `insurance/attachment_assembler.py` (FULL, X12 275 + PWK, refuses to declare an attachment it isn't sending), `insurance/document_request_gate.py` (gate, fires ONLY for records the AI can't find). This is the largest automatable slice in the claim path: most requests are satisfiable from documents the practice already holds |
| Claim status / denial detection | `shared/payer_outcomes.py` (classifies 8 denial reasons into 5 actions — only 2 are appeals), `billing/denial_detector.py` (FULL, post-ERA in the reconciliation domain), `billing/denial_appeal_handler.py` (gate, opens only when an appeal or documentation-resubmission is actually the right move) |
| Remittance & payment posting | `billing/payment_processor.py`, `billing/invoice_generator.py`, `billing/reconciliation_statement.py` (all FULL) |
| **Not quantified (no benchmark used):** scheduling, intake, reminders, pharmacy ops, fraud detection | `scheduling/*`, `patient/*`, `pharmacy/*`, `fraud/*` — real workload, but no published per-transaction benchmark was used, so **excluded** (model is conservative) |

---

## 3. Assumptions table

| ID | Assumption | Value | Basis |
|----|-----------|-------|-------|
| A1 | Practice size | 10-dentist group practice, 40,000 encounters/yr | Given (user-defined scenario; a multi-location group/DSO-scale practice) |
| A2 | Working weeks/yr | 48 | ASSUMPTION (standard practice-ops convention) |
| A3 | Loaded staff cost | $26.91 × 1.42 ≈ **$38/hr** | S8 wage ÷ 0.703 wage-share (S9) |
| A4 | Share of eligibility checks still involving manual/portal staff work | 20% | ASSUMPTION (conservative; CAQH S2 notes portal work persists even where EDI exists) |
| A5 | Share of claims getting a manual status inquiry | 20% | ASSUMPTION (CAQH S2: phone inquiry = 25 min, "we primarily call" provider quote; plan-side electronic adoption ~80%) |
| A6 | Share of claims still manually submitted | 2% | S2 (98% electronic adoption) |
| A7 | Share of remits/payments manually posted | 11% | S2 (ERA adoption 89%) |
| A8 | Automatable share of PA time | 58.3% | S2: electronic saves 14 of 24 manual minutes (14/24) |
| A9 | Initial denial rate | 10–12% | S5 |
| A10 | Denial causes addressable by these agents | 40–60% of denials | S4 (data errors ~46–50%, PA 35%, registration 32%; multi-select/overlapping, so a 40–60% band is used rather than summing) |
| A11 | Prevention effectiveness on addressable denials | 60–75% | ASSUMPTION, bounded below the 86–90% "preventable" ceiling (S7) |
| A12 | LLM tokens per agent call | 1,500 in / 400 out | ASSUMPTION (output capped by `LLM_MAX_TOKENS=512` in `.env.example`) |
| A13 | LLM-calling agents per encounter | 6 | Verified in code: `RequestParser`, `SymptomRecorder`, `DiagnosisSuggester`, `ClinicalNoteTranscriber`, `ClaimNarrativeWriter`, `ConsistencyChecker` are the only agents constructed with `self.llm` (`grep "self\.llm" src/agents/*/orchestrator.py`) |
| A14 | Gate-resume pipeline replays per encounter | ~5 (4 always-fire gates + pharmacist verification when a script exists) | Verified in code: `src/core/orchestrator/gate.py` (resume = full pipeline re-run); always-on gates: `slot_selection`, `consent_signature`, `diagnosis_signoff`, `patient_payment_authorization` |

---

## 4. (a) Administrative hours reclaimed annually

### 4.1 Prior authorization
Two independent methods, using S1 + S2:

- **Method 1 (AMA burden × CAQH automatable share, cross-applied to dental — see caveat above):**
  13 hr/wk (S1) × 10 dentists × 48 wk (A2) = **6,240 hr/yr** total PA burden.
  6,240 × 58.3% (A8) = **3,640 hr/yr** reclaimed.
- **Method 2 (AMA volume × CAQH per-transaction saving):**
  40 PAs/wk (S1) × 10 × 48 = 19,200 PAs/yr.
  19,200 × 14 min (S2) = 268,800 min ÷ 60 = **4,480 hr/yr** reclaimed.

→ **PA range: 3,640–4,480 hr/yr** (clinical necessity decision remains human via `predetermination_review` gate — that time is *not* counted as reclaimed).

### 4.2 Eligibility & benefit verification
40,000 encounters × 20% (A4) = 8,000 manual checks × 12 min (S2) = 96,000 min = **1,600 hr/yr**.

### 4.3 Claim submission
40,000 claims × 2% (A6) = 800 × 7 min (S2) = 5,600 min = **93 hr/yr**.

### 4.4 Claim status inquiry
40,000 claims × 20% (A5) = 8,000 inquiries × 18 min (S2) = 144,000 min = **2,400 hr/yr**.

### 4.5 Remittance advice + payment posting
40,000 × 11% (A7) = 4,400 × (4 + 3) min (S2) = 30,800 min = **513 hr/yr**.

### Total hours
| Component | Low | High |
|---|---|---|
| Prior authorization | 3,640 | 4,480 |
| Eligibility | 1,600 | 1,600 |
| Claim submission | 93 | 93 |
| Claim status | 2,400 | 2,400 |
| Remit/payment posting | 513 | 513 |
| **Total** | **8,246** | **9,086** |

→ **≈ 8,200–9,100 hours/yr ≈ 4.1–4.5 FTEs** (at 2,000 hr/FTE).

*Why this is far below the old 26,000-hr claim:* that figure implicitly assumed a fully manual baseline across all transactions. CAQH adoption data (S2) shows claim submission is already 98% electronic and ERA 89%, so an honest model only credits the residual manual share plus PA/status/eligibility work that is still genuinely manual. Scheduling/intake/pharmacy/fraud work the system also does was excluded entirely (no benchmark), so this is a floor, not a ceiling.

## 5. (b) Dollar value of reclaimed capacity

- Hours × loaded staff rate (A3): 8,246 × $38 = **$313,348**; 9,086 × $38 = **$345,268**.
- Denial-rework avoidance (see §6): +$43,840 to +$123,617.

→ **Total ≈ $357K–$469K per year** (headline: **~$355K–$470K**).

*Sensitivity (not in headline):* AMA's 13 hr/wk includes physician (here, cross-applied as dentist) time; valuing that share at a dentist's chair-time rate instead of $38/hr would raise the total meaningfully, but the dentist/staff split is not published, so it is left out.
*Why this is far below the old $3.9M–$5.2M claim:* at a $38/hr loaded clerical rate, $3.9M would require ~103,000 staff hours — 51 full-time staff doing nothing but these tasks in a 10-dentist practice. Not defensible.

## 6. (c) Claim-denial reduction

- Initial denials: 40,000 × 10–12% (A9) = **4,000–4,800 denials/yr**.
- Addressable by these agents (A10, from S4 causes ↔ §2 mapping): 40–60%.
- Prevention effectiveness (A11): 60–75%.
- Combined reduction: 0.40 × 0.60 = 24% (low) … 0.60 × 0.75 = 45% (high).

→ **Modeled ~25–45% (24–45%) reduction in initial denials** (vs. old claim of 30–50% — keep the new band).
- Avoided denials: 4,000 × 25% = 1,000 (low) … 4,800 × 45% = 2,160 (high).
- Rework cost avoided (S6): 1,000 × $43.84 = **$43,840** … 2,160 × $57.23 = **$123,617**.
(Faster-cash / recovered-revenue effects are real but not modeled — no clean benchmark.)

## 7. (d) LLM inference cost reduction (dynamic provider routing)

Mechanism verified in code: `src/core/llm/client.py` — provider-agnostic client routing to `groq | gemini | anthropic` with automatic fallback (`llm_fallback_provider`) and per-encounter response caching; only 6 of 76 agents make LLM calls (A13). Notably, the treatment plan itself (which procedures get recommended) is a deterministic lookup, not a model call — `treatment_plan_builder.py`.

Per-encounter tokens (A12 × A13): 6 calls × (1,500 in / 400 out) = 9,000 in / 2,400 out.

| Provider (published price, in/out per 1M) | Cost per encounter | vs. Sonnet baseline |
|---|---|---|
| Claude Sonnet 4.5 — $3.00/$15.00 (S11) | 9,000×$3/1M + 2,400×$15/1M = $0.027 + $0.036 = **$0.0630** | baseline |
| Groq Llama-3.3-70B — $0.59/$0.79 (S10) | $0.00531 + $0.00190 = **$0.0072** | **−88.6%** |
| Gemini 2.5 Flash — $0.15/$1.25 (S12) | $0.00135 + $0.00300 = **$0.0044** | **−93.1%** |

- Full routing to low-cost providers: **87–93% reduction** at published prices. (The percentages are ratio-driven, so adding the two documentation agents changed the absolute cost but not the reduction band.)
- Mixed routing (70% low-cost / 30% frontier for hard cases): ≈ 0.7 × 0.90 ≈ **~60–65%**.
- **Caching bonus** (separate mechanism): every human-gate resume re-runs the pipeline (`gate.py`); with ~5 replays per encounter (A14), caching cuts ~36 potential LLM calls to 6 ≈ **~80% fewer calls** in gated flows.

→ Honest headline: **60–93% lower inference cost depending on routing mix** (old claim of 40–70% was *understated* on pure routing, but see the caveat).
**Caveat to volunteer in interviews:** absolute LLM spend at this scale is small — ~$2,520/yr all-frontier vs ~$175–290/yr routed (40,000 × table above). The percentage is real; the dollar impact is not the headline value driver. The architecture matters more at higher volume or with heavier prompts — and the narrative writer is the one agent whose prompt is genuinely heavy, since it carries the chart note plus findings.

---

## 8. Summary box — resume-ready figures

```
VERIFIED SYSTEM (counted in this codebase, updated 2026-08-02)
• 76 single-task sub-agents across 8 domain orchestrators + 1 master orchestrator
  (82 pipeline-step executions per full encounter)
• 15 human-in-the-loop pause/resume gates (7 mandated by law/regulation,
  3 inherent patient actions, 5 policy/judgment reviews)
• 62% of agent functions fully automated today (47/76); 78% run autonomously
  incl. AI-draft/human-verify (59/76); documented ceiling ≈90% (69/76) with a
  10% legally-mandated human floor (7/76)
• A real diagnose → dentist-reviewed treatment plan → patient-consented,
  per-line-item flow, and a real claim-submission → payer-remittance (ERA/CARC
  codes) → reconciliation flow — not single-code approximations of either
• Domain order matches actual US dental-practice mechanics: eligibility verified
  PRE-VISIT, the patient charged an ESTIMATE at checkout BEFORE any claim is
  filed, then that estimate reconciled against the 835 ERA into a balance bill
  or a refund (see docs/us-dental-clinic-real-world-workflow.md)

MODELED IMPACT (10-dentist group practice, 40,000 encounters/yr — published benchmarks
cross-applied from medical RCM studies; see dental cross-application caveat)
• ~8,200–9,100 administrative hours reclaimed per year (≈4.1–4.5 FTEs)
• ~$355K–$470K annual administrative value
• Modeled 25–45% reduction in initial claim denials
• 60–93% lower LLM inference cost vs. single frontier-model deployment
  (published Jul-2026 prices), plus ~80% fewer LLM calls in gated flows
  from resume-replay caching
```

Suggested resume phrasing: *"Modeled on AMA/CAQH medical-RCM benchmarks cross-applied to a dental group practice: ~8,000–9,000 admin hours (~4 FTEs, ~$355–470K) reclaimed annually for a 10-dentist practice, with a 25–45% modeled reduction in initial claim denials; provider-agnostic LLM routing cuts inference cost 60–93% at published prices."*

---

## Appendix — verified codebase counts (evidence paths)

| Metric | v1 (resume claim) | v1 (counted today) | Current build (counted today) | Where counted |
|---|---|---|---|---|
| Sub-agents | 34 | 37 functional wired steps (+7 domain audit loggers = 44 steps); a code comment says "36 sub-agents" | **76 unique wired agent classes** (77 in repo; `scheduling/audit_logger.py` unwired; 82 pipeline steps incl. shared audit agent ×8, plus 1 post-visit recall step outside any domain's step list) | v1: `Executable files/files/healthcare-ai/src/agents/*/orchestrator.py` · current: `src/agents/*/` + `src/agents/*/orchestrator.py` |
| Domain orchestrators | 7 | 7 wired ✓ | **8** (+1 `MasterOrchestrator`) — billing split into `CheckoutOrchestrator` and `ReconciliationOrchestrator` to match the real two-phase bill | `src/agents/*/orchestrator.py`, `src/agents/billing/reconciliation_orchestrator.py`, `src/core/pipeline/master_orchestrator.py` |
| Tests | 918 | 945 `def test_` functions (claim consistent with an earlier snapshot; no git history to confirm) | **195** collected tests, 23 files, all passing | v1: `…/healthcare-ai/tests/` · current: `tests/` |
| API endpoints | 5 | 5 ✓ (3 encounter + 2 health) | **6** (4 encounter + health + `/` UI) | `src/api/app.py` |
| Frontend files | 31 | 33 files excl. node_modules (31 excl. package/lock) | **1** (`web/index.html`) | v1: `…/healthcare-ai/frontend/` · current: `web/` |
| HITL flows | 2 | 2 ✓ (doctor selection, billing patient approval) | **15 gates** on one pause/resume primitive | v1: `doctor_selector_agent.py`, `patient_approval_agent.py` · current: `grep HumanGateAgent src/agents/`, `src/core/orchestrator/gate.py` |
| TDD phases | 17 | 18 step folders (step5a–step16) + step1–4 artifacts; exact "17" not reproducible | n/a (rewrite, no step folders) | `Executable files/` |
| Regulatory tier split | 29 / 3 / 2 | no tier metadata in v1 code — **not verifiable** | **47 FULL / 12 PARTIAL / 17 gates**; gates: 7 law/reg (diagnosis sign-off, treatment-plan review, EPCS signing [21 CFR 1311], pharmacist verification [OBRA-90], consent signature, critical-value acknowledgment, predetermination clinical review), 3 patient actions (slot selection, treatment consent, payment authorization), 5 policy/judgment (coding QA, denial appeal, MPI conflict, SIU review, referral approval) | `grep "Automation\." src/agents/`, gate docstrings in each `HumanGateAgent` file |

Notes: (1) v1 has no git repo, so v1 numbers were counted from the `Executable files/files/healthcare-ai/` snapshot as it exists today — small deltas vs. resume claims (918→945 tests, 31→33 files, 34→37 agents) are consistent with post-resume edits but cannot be proven without history. (2) Current-build README states "82 pipeline-step executions"; that counts steps (shared audit agent ×8 plus one post-visit step) — the unique-class count above (76) is the defensible one, and `/health`'s `agents` field is computed live from orchestrator step counts rather than hand-maintained, specifically to prevent this kind of figure drifting out of sync with the code again. (3) The 2026-08-02 domain reordering (eligibility moved pre-visit; billing split into checkout + reconciliation) added one net agent class (`reconciliation_statement`) and two net pipeline steps; it did not add or remove any human gate.
