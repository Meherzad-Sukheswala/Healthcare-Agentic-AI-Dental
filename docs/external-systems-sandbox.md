# External Systems Simulated by the Sandbox

The application's integration layer defines standards-shaped "ports" (interfaces) for every external system a real healthcare encounter pipeline would call. Each port has a high-fidelity **sandbox** implementation for offline, deterministic demos, plus a drop-in slot for a real vendor later — so switching any subsystem from simulated to real is a single change in `build_registry`, with no agent code touched.

The sandbox currently simulates the following 11 external systems:

| # | System | Real-world standard / vendor | What it does |
|---|--------|------------------------------|--------------|
| 1 | EHR / practice management | FHIR R4 electronic record (a dental PMS such as Dentrix, Eaglesoft, Open Dental, or Curve Dental in production — not a hospital EHR like Epic) | Reads patient records and writes clinical notes. The one subsystem that can be flipped to a real public FHIR server via `EHR_MODE=fhir_public`. |
| 2 | Eligibility & benefits | X12 270/271 transactions | Checks a patient's dental insurance coverage (copay, coinsurance, deductible). Driven by the insurance selector. |
| 3 | Predetermination | X12 278 | Submits a voluntary pre-treatment estimate request for high-cost/surgical procedures (implants, bone grafts, comprehensive ortho) — advisory, not a mandatory gate on treatment the way medical prior-auth is. |
| 4 | Claims + remittance | ADA Dental Claim Form / X12 837D submission + X12 835 electronic remittance advice (ERA) | Files the claim (the clinic's request for payment) after the visit, coded in CDT, with multiple procedures on one claim when applicable — then receives the payer's response: paid amount, contractual write-off, and CARC adjustment reason codes. |
| 5 | Provider directory | NPPES (national NPI registry) | Finds doctors by specialty and looks them up by NPI. |
| 6 | Drug information | First Databank / Micromedex-style reference | Checks drug-drug interactions, cross-allergies, and formulary status. |
| 7 | Pharmacy network | NCPDP SCRIPT / Surescripts | Sends e-prescriptions, checks stock, and dispatches the order. |
| 8 | DEA EPCS | Controlled-substance electronic signing (two-factor auth) | The gate the "Controlled Rx" scenario triggers. |
| 9 | PDMP | State Prescription Drug Monitoring Program | Queries a patient's controlled-substance history for risk flags. |
| 10 | Scheduling | Per-provider availability calendars | Working hours minus existing bookings; the appointment-slot source. |
| 11 | Payment | Healthcare-grade payment processor | Charges the patient's amount due (the payment authorization gate). |

## Real-world vendors by category

These are representative real companies/products in each category. The sandbox does not integrate any of them — it simulates the category. A few are named explicitly in `ports.py`.

| # | System (standard) | Real-world companies / products |
|---|-------------------|---------------------------------|
| 1 | EHR / PMS (FHIR R4) | Dentrix (Henry Schein One); Eaglesoft (Patterson); Open Dental; Curve Dental; Denticon (Planet DDS). Demo's real mode uses **HAPI FHIR** (public test server) since no dental PMS exposes a public FHIR sandbox. |
| 2 | Eligibility & benefits (X12 270/271) | DentalXChange; Vyne Dental (formerly Trellis/ClaimConnect); Tesia; Availity; Optum (absorbed Change Healthcare) — the last two also handle dental, just not dental-first |
| 3 | Predetermination (X12 278) | DentalXChange; Vyne Dental; Availity; Optum/Change Healthcare |
| 4 | Claims + remittance (ADA Dental Claim / X12 837D + X12 835 ERA) | DentalXChange; Vyne Dental; Tesia; Availity; Optum/Change Healthcare |
| 5 | Provider directory (NPPES) | NPPES run by **CMS** (US government); CAQH; LexisNexis Health Care |
| 6 | Drug information | First Databank (FDB); Micromedex (Merative); Medi-Span & Lexicomp (Wolters Kluwer); Elsevier/Gold Standard |
| 7 | Pharmacy network (NCPDP SCRIPT / Surescripts) | Surescripts (dominant e-prescribing network); NCPDP (standards body); PBMs: CVS Caremark, Express Scripts (Cigna), OptumRx |
| 8 | DEA EPCS (controlled-substance e-signing + 2FA) | DrFirst; Imprivata; Surescripts |
| 9 | PDMP | State-run programs aggregated by **Bamboo Health** (formerly Appriss Health) — PMP Gateway / NarxCare |
| 10 | Scheduling | PMS-embedded (Dentrix, Eaglesoft, Open Dental native scheduling); patient-facing: NexHealth, Weave, Zocdoc |
| 11 | Payment | InstaMed (owned by JPMorgan); Waystar; Cedar; Flywire Health — on top of card networks |

**Recent ownership changes worth noting:** Cerner → **Oracle Health**; Change Healthcare → part of **Optum** (UnitedHealth Group); Allscripts' provider business → **Veradigm**; Appriss Health → **Bamboo Health**; Micromedex → owned by **Merative**.

## Notes

- **Why a sandbox is used:** it lets the demo run end-to-end with no real integrations, no credentials, and no real patient data (PHI) — safer, legal, and HIPAA-friendly — while staying deterministic so demos and tests are reproducible.
- **Real vs. simulated today:** the four LLM agents run on a real model (Gemini, with Groq fallback), but every external system above is simulated by the sandbox. Only the EHR read can currently be switched to a real source (`EHR_MODE=fhir_public`).
- **Source:** interfaces are defined in `src/integrations/ports.py`; sandbox implementations in `src/integrations/sandbox.py`; wiring in `src/integrations/registry.py` (`build_registry`).
