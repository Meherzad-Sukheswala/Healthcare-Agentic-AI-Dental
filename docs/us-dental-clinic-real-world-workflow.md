# How a Real US Dental Clinic Runs — Systems, Data, Money, and the People in the Loop

Research compiled 2026-08-02. Scope: a general dental practice in the United States, from
the moment a patient wants an appointment to the moment the last dollar is collected and the
prescription is picked up. Written as a reference for the agentic-AI build in this repo, so
each section ends with **→ Repo delta**: how the real world differs from what
`src/agents/` currently models.

Sources are listed at the end of each major section. Where a figure comes from a
non-US study or a vendor's own marketing, that is labeled inline.

---

## 0. Four corrections to the intuitive mental model

Before the detail, four places where the obvious sequence is wrong. These matter because
this repo's pipeline currently encodes the intuitive version.

### 0.1 The patient is billed *before* the insurer approves anything

The intuitive flow is: treat → bill insurer → insurer approves → collect from patient.
The real flow in general dentistry is:

```
verify eligibility (pre-visit)
  → dentist diagnoses and plans treatment
  → software computes an ESTIMATE of the patient's share
  → patient pays that estimate AT THE APPOINTMENT, before leaving
  → claim goes to the payer the same day or that evening
  → payer adjudicates 3–14 days later, sends money + an ERA
  → office posts the ERA, discovers the estimate was off by some amount
  → patient gets a balance statement, or a refund
```

There is no approval gate between treatment and collecting from the patient. The office
takes financial risk on the accuracy of its own estimate, and the *patient's true
out-of-pocket is not known on the day of service*. Almost all downstream billing pain in
dentistry — balance bills, refunds, angry phone calls, AR aging — comes from the gap
between the estimate and the ERA.

### 0.2 Dental has *predetermination*, not prior authorization

Medical prior auth is mandatory and blocking: no auth, no coverage. Dental
**predetermination** (also "pre-treatment estimate," "pre-D") is:

- **Voluntary.** The payer may encourage it; it is not required for coverage.
- **Non-binding.** The returned amounts are estimates based on eligibility and remaining
  benefits *as of the day it was processed*. If the patient's coverage or remaining annual
  maximum changes before the real claim lands, the payment changes.
- **Selective.** Used mostly for high-cost work: crowns, bridges, dentures, implants,
  perio surgery, orthodontics, third-molar extractions.
- **Slow.** It is a full claim round-trip, so treatment is typically deferred 2–4 weeks
  while it comes back.

Real, mandatory, blocking prior authorization *does* exist in dentistry — but only on the
**medical cross-coding** path (§7.7), where a dental office bills a patient's *medical*
plan for something like a CBCT scan, an oral sleep appliance, or medically necessary oral
surgery. Different form, different code set, different payer, different rules.

### 0.3 Nobody contacts a "nearby pharmacy"

There is no dispatch, no delivery, and no clinic-side order tracking. The actual flow:

1. The dentist asks the patient which pharmacy they use. The patient names one.
2. The prescription is transmitted over the **Surescripts** network as an NCPDP SCRIPT
   `NewRx` message addressed to *that specific pharmacy's* NCPDP ID.
3. The pharmacy receives it in its own dispensing system, adjudicates it against the
   patient's *pharmacy* benefit (a PBM — an entirely separate insurer from the dental
   plan), fills it, and puts it on the shelf.
4. The patient walks in and picks it up, possibly days later, possibly never.

The clinic does not know whether the prescription was ever filled unless the pharmacy
sends an optional `RxFill` notification, which most retail pharmacies do not. In-office
dispensing of drugs is rare in general dentistry and heavily state-regulated.

### 0.4 There is no single "the dental software"

A working practice runs 6–10 separate systems glued together. The PMS is the system of
record, but it does not do imaging, claims transport, patient texting, card processing, or
e-prescribing. Each of those is a different vendor with a different integration
mechanism — a bridge, a plugin, an API, or in the worst case a staff member retyping
between two screens.

---

## 1. Everyone in the loop

### 1.1 Inside the practice

| Role | Credential | What they own | Systems they touch |
|---|---|---|---|
| **Patient / caregiver** | — | Requests care, supplies history and insurance, consents, chooses treatment options and payment method, chooses the pharmacy | Booking widget, forms link, text reminders, payment link, portal |
| **Front desk / scheduling coordinator** | — | Answers phones, books and confirms, checks in/out, collects payment, manages the schedule's holes | PMS scheduler, comms platform, payments terminal |
| **Hygiene / recare coordinator** | — | Recall lists, reactivation of overdue patients, pre-appointing the next 6-month visit | PMS recall module, comms platform, analytics |
| **Insurance / billing coordinator** | often CDC or billing cert | Eligibility verification, breakdowns, claim creation and submission, attachments, ERA posting, denials, appeals, AR follow-up | PMS ledger + claims, clearinghouse portal, payer portals, attachment service |
| **Treatment coordinator (TC)** | — | Presents the treatment plan and its cost, sequences it into phases and visits, closes the case, arranges financing | PMS treatment planner, estimate/presentation view, financing app |
| **Financial coordinator** | — | Payment arrangements, statements, collections, refunds (often the same person as the TC in a small office) | PMS ledger, statements, processor portal |
| **Dental assistant** | DA / CDA / RDA / EFDA (state-varying) | Seats the patient, updates medical history, takes radiographs, assists chairside, sterilization, some states place restorations | PMS clinical chart, imaging software, sensor |
| **Dental hygienist** | **RDH**, licensed | Prophylaxis, scaling/root planing, perio charting, radiographs, oral cancer screening, patient education, flags findings for the dentist | PMS perio module, imaging, clinical notes |
| **Dentist** | **DDS / DMD**, state-licensed, DEA-registered | The only person who may diagnose, prescribe, and sign off treatment. Owns the treatment plan and every clinical note | Everything clinical, e-Rx, EPCS token |
| **Specialist** (endodontist, periodontist, oral surgeon, prosthodontist, orthodontist, pediatric dentist) | DDS/DMD + residency | Referred-out portions of the plan; runs their own separate practice, chart, and claims | Their own PMS; referral portal or fax |
| **Dental lab technician** | CDT (cert., optional) | Fabricates crowns, bridges, dentures, appliances from the dentist's Rx and impressions/scans | Lab portal, digital-impression file transfer |
| **Office manager / practice administrator** | — | Staffing, AR oversight, fee schedules, payer contracts, vendor contracts. Usually the **HIPAA Privacy/Security Officer** | Every system, plus reporting |
| **Owner dentist / DSO regional manager** | DDS/DMD / MBA | Fee schedules, which plans to accept, capital equipment, protocols | Analytics dashboards |

### 1.2 Outside the practice

| Role | Where they sit | What they decide |
|---|---|---|
| **Clearinghouse operations** | DentalXChange, Vyne Dental, Tesia, Availity, Optum (ex-Change Healthcare) | Scrubs and routes the claim; rejects malformed claims *before* the payer sees them |
| **Payer claims examiner** | Insurance carrier | Processes claims that fail auto-adjudication |
| **Payer dental case management** | Licensed hygienists and assistants employed by the carrier | First-pass clinical review of radiographs and narratives |
| **Payer dental consultant** | Licensed general dentist or specialist, contracted by the carrier | Judges clinical criteria — e.g. whether enough tooth structure was lost to justify a crown rather than a filling |
| **Payer dental director** | DDS/DMD, carrier employee | Supervises case management and consultants; sets clinical policy; final internal appeal authority |
| **Outsourced biller / RCM vendor** | Remote, often offshore, logged into the practice's PMS | Increasingly *is* the insurance coordinator, especially for DSOs |
| **Pharmacist** | RPh / PharmD, retail pharmacy | Independent professional judgment on every prescription: DUR, interactions, allergies, dose, therapeutic appropriateness. **Can refuse to fill.** |
| **Pharmacy technician** | state-registered | Data entry, counting, labeling, insurance troubleshooting |
| **PBM** | CVS Caremark, Express Scripts, OptumRx | Adjudicates the *drug* claim — a different benefit, deductible, and formulary from the dental plan |
| **State PDMP** | State agency, mostly via Bamboo Health's PMP Gateway | Controlled-substance dispensing history the prescriber must check in most states |
| **Payment processor** | InstaMed, Rectangle Health, Weave Payments, Global Payments | Card authorization, settlement, PCI scope |
| **Patient financing underwriter** | CareCredit (Synchrony), Sunbit, Cherry | Approves or declines patient credit in ~60 seconds at chairside |

**Sources:** [DentistryIQ on front-office coordinator roles](https://www.dentistryiq.com/front-office/article/14297710/calling-all-coordinators-defining-various-dental-front-office-admin-roles) ·
[Teero: what a treatment coordinator does](https://www.teero.com/blog/what-is-a-treatment-coordinator) ·
[Delta Dental: X-ray and clinical review guidance](https://www.deltadentalins.com/dentists/guidance/x-rays.html) ·
[Delta Dental dentist FAQ (case management, dental director, consultants)](https://www1.deltadentalins.com/faqs/dentists.html) ·
[Group Dentistry Now on dental RCM outsourcing](https://www.groupdentistrynow.com/dso-group-blog/dental-rcm/)

---

## 2. The software stack

| Layer | Function | Real vendors | Standard / protocol |
|---|---|---|---|
| **Practice management (PMS)** — system of record | Scheduler, patient/family ledger, odontogram, clinical notes, treatment plans, claims, reports | **Server-based:** Dentrix (Henry Schein One), Eaglesoft (Patterson), PracticeWorks/SoftDent (Carestream). **Cloud:** Open Dental (self-host or hosted), Curve Dental, Denticon (Planet DDS), Dentrix Ascend, CareStack, tab32, Oryx, iDentalSoft | Mostly proprietary. Open Dental exposes a documented MySQL schema and REST API — which is why almost every third-party dental tool integrates with it first |
| **Imaging** | Sensor/pano/CBCT capture, viewing, measurement, comparison | DEXIS (Envista), Carestream CS Imaging, Planmeca Romexis, Sirona Sidexis 4, VixWin, Apteryx XVWeb/X-Vue (cloud) | **DICOM** for 3D/CBCT; 2D intraoral often stored as proprietary + JPEG/TIFF. PMS↔imaging connection is a **bridge** launching the imaging app in patient context, not a data merge |
| **Clearinghouse** | Eligibility, claim transport, claim status, ERA delivery | DentalXChange (900+ payers, integrated with Open Dental/Dentrix/most PMS), Vyne Dental (incl. ClearCoverage real-time eligibility), Tesia, Availity, Optum, Stedi (API-first) | X12 **270/271** eligibility, **276/277** status, **837D** claim, **835** ERA — HIPAA 5010 |
| **Claim attachments** | Send radiographs, perio charts, photos, narratives with the claim | **NEA FastAttach** (Vyne) — 50,000+ providers, 750+ payer connections; some clearinghouses have native attachment | 837D **PWK segment** carrying an **NEA# attachment control number** (e.g. `NEA#A12345678`) |
| **Patient communication / engagement** | Two-way SMS, appointment confirmations, recall campaigns, reactivation, review requests, digital forms, online booking, VoIP | Weave (bundled into Eaglesoft since a Jan 2025 Patterson partnership), NexHealth, RevenueWell, Solutionreach, Lighthouse 360, Doctible, Dental Intelligence, Modento | Proprietary; writes appointments back into the PMS scheduler in real time |
| **Payments** | Card present/not-present, text-to-pay, card on file, payment plans | InstaMed (JPMorgan), Rectangle Health, Weave Payments, Global Payments Integrated | PCI-DSS; healthcare processors handle patient-responsibility settlement and refunds |
| **Patient financing** | Third-party credit so the patient can accept the plan today | CareCredit/Synchrony (270k+ practices, lines to ~$25k), Sunbit (87% approval, fees from ~1.9%/txn, no hard pull — vendor figures), Cherry (~90% approval, up to $50k, 0% APR if paid on time — vendor figures) | Proprietary; increasingly embedded in the PMS (e.g. CareStack + Sunbit) |
| **E-prescribing** | Transmit Rx, drug interaction/allergy checking, EPCS signing, PDMP lookup | DoseSpot, iCoreRx, Veradigm ePrescribe, DrFirst/Rcopia, NewCrop — surfaced *inside* the PMS (Open Dental, Dentrix, Curve all embed one) | **NCPDP SCRIPT** over Surescripts; **DEA EPCS** (21 CFR 1311) identity proofing + two-factor; PDMP via Bamboo Health PMP Gateway |
| **Analytics / RCM reporting** | Production, collection %, AR aging, unscheduled treatment, recall gaps, downgrade tracking | Dental Intelligence, Practice by Numbers, Jarvis (DSO), Divergent | Reads the PMS database |
| **AI adjuncts (newer)** | Radiographic caries/bone-loss detection, voice perio charting, ambient clinical notes, automated insurance verification | Overjet, Pearl, VideaHealth; voice charting native in several PMSs | Bolt-on; sits between imaging and the chart |
| **Backup / DR** | HIPAA-compliant encrypted backup, ransomware-resistant copies | Datto, Carbonite, NovaBACKUP, Central Data Storage | **3-2-1 rule** (3 copies, 2 media types, 1 offsite), encryption in transit and at rest, immutable/air-gapped copies |

Market context: the dental PMS market is ~**$2.62B in 2026**, growing ~**11.1% CAGR** toward
~$4.44B by 2031, with Henry Schein One, Patterson, Carestream Dental, and Planet DDS holding
the largest shares. Per-vendor share percentages are not published in the sources reviewed —
treat any specific "% of practices use X" claim with suspicion.

**Sources:** [Mordor Intelligence: dental PMS market](https://www.mordorintelligence.com/industry-reports/dental-practice-management-software-market) ·
[Siotek PMS comparison 2026](https://siotek.net/resources/dental-practice-management-software-comparison) ·
[DentalXChange vs Vyne vs Stedi](https://avized.com/insights/dentalxchange-vs-vyne-dental-vs-stedi-clearinghouse-2026) ·
[Vyne Dental payer connections](https://vynedental.com/payers/) ·
[Vyne FastAttach](https://vynedental.com/fastattach/) ·
[Ventus AI: NEA attachment / PWK segment](https://www.ventus.ai/glossary/dental-claim-attachment-nea/) ·
[Curve: imaging bridges](https://www.curvedental.com/blog/how-does-curve-streamline-the-clinical-workflow) ·
[TitanWeb: dental imaging software](https://blog.titanwebagency.com/dental-imaging-software) ·
[Accountable HQ: HIPAA backup for dental](https://www.accountablehq.com/post/data-backup-best-practices-for-dental-offices-a-hipaa-compliant-ransomware-ready-guide) ·
[Sunbit vs CareCredit](https://withcherry.com/blog/sunbit-vs-carecredit) ·
[Sunbit for dental](https://sunbit.com/merchant-benefits/dental/)

---

## 3. Domain 1 — Scheduling and the pre-visit runway

### 3.1 How the appointment actually gets made

Four intake channels, in rough order of volume:

1. **Phone.** Still dominant. Front desk answers, checks the schedule, books.
2. **Online booking widget.** The patient picks from real open slots and the appointment
   writes back into the PMS scheduler instantly — no callback required.
3. **Recall / recare.** The PMS knows every patient's next-due hygiene date. Automated
   campaigns text and email them at intervals. This is the single largest source of
   appointments in a mature practice.
4. **Referral.** From a general dentist to a specialist, or from an ER/physician. Arrives
   as a fax, a portal message, or a phone call.

### 3.2 The schedule is not a flat calendar

It is a grid of **columns** — one per operatory or per provider. A two-dentist,
three-hygienist practice has five columns. Two structural facts drive everything:

- **Hygiene columns are booked 3–6 months out** (recall-driven, highly predictable).
- **Doctor columns are booked days-to-weeks out** (treatment-driven, unpredictable).

**Block scheduling** reserves specific time windows for specific appointment types — a
crown-prep block in prime morning time, emergency slots held open at 11am and 4pm, new-patient
consults after lunch — so the front desk isn't filling a $1,800 crown slot with a $60
periodic exam just because that call came in first.

### 3.3 Appointment length is a clinical decision

Procedure type determines chair time: periodic exam + prophy 45–60 min; SRP per quadrant
60 min; crown prep 60–90 min; extraction 30–60 min; new-patient comprehensive exam
60–90 min. Booking the wrong length wrecks the rest of the day. In practice the front desk
uses PMS procedure-time templates, and the assistant or hygienist corrects them.

### 3.4 Confirmation and no-show management

Automated reminders at ~1 week, ~48h, and ~24h, with a one-tap confirm or reschedule link.
Confirmed status updates on the PMS calendar automatically. Practices track no-show and
short-notice cancellation rates separately; sustained rates above roughly **5–8%** are
taken as a signal that the reminder cadence itself is broken rather than that patients are
unreliable. Offices keep an ASAP/short-call list to backfill same-day holes.

### 3.5 The pre-visit insurance runway — the most under-modeled step

This is where the practice does most of its financial risk management, 1–3 days *before*
the patient arrives:

1. **Eligibility check.** An X12 **270** goes to the payer via the clearinghouse; a **271**
   comes back in seconds confirming active coverage, plan type, effective dates, and gross
   benefit levels.
2. **The breakdown gap.** The 271 typically returns coverage *categories* and remaining
   maximum — not the procedure-level detail the office needs to build an accurate estimate.
   Frequency limits, waiting periods, downgrade clauses, missing-tooth clauses, and
   per-code percentages usually require a **payer portal lookup or a phone call**. A full
   manual breakdown takes 10–20 minutes per patient. This one gap is why "AI insurance
   verification" is currently the hottest product category in dental software.
3. **Fee schedule confirmation.** For in-network plans, the office loads the payer's
   contracted fee schedule into the PMS so estimates use the *allowed* amount, not the
   office's full fee.
4. The verified breakdown is attached to the patient's record so the treatment coordinator
   and the estimate engine can use it.

**→ Repo delta.** `src/agents/scheduling/` models request parsing, provider matching by
specialty, availability, slot selection (human gate), booking, reminders, and a post-visit
recall — which maps well. Three things missing: (a) **appointment duration is not derived
from procedure type**, so slot selection is length-agnostic; (b) the **column/operatory
model** doesn't exist, so there's no hygiene-vs-doctor capacity distinction; (c) the
**pre-visit eligibility runway is in the wrong domain** — `patient/eligibility_verifier.py`
and `insurance/eligibility_checker.py` run *after* scheduling and *during* the encounter,
whereas in reality verification happens days before the visit and its output is a
precondition for accurate estimating. Also, `recall_scheduler` correctly runs post-visit,
but real recall is a *standing background process* that re-queries the whole patient base
daily, not a per-encounter step.

**Sources:** [Dentrix Ascend: scheduling efficiently](https://www.dentrixascend.com/insights/blogs/schedule-dental-appointments-efficiently/) ·
[Practice by Numbers: reducing no-shows](https://practicenumbers.com/blog/dental-office-scheduling-software-how-to-reduce-no-shows/) ·
[Emitrr: online scheduling for dental offices](https://emitrr.com/blog/online-scheduling-for-dental-office/) ·
[Needletail: dental eligibility verification software 2026](https://www.needletailai.com/blog/best-practices/dental-insurance-eligibility-verification-software) ·
[US Tech Automations: verification automation](https://ustechautomations.com/resources/blog/dental-insurance-verification-automation)

---

## 4. Domain 2 — Patient data: intake, identity, and the record

### 4.1 New-patient intake

Digital forms sent by text/email before the visit (or on an office iPad):

- Demographics, responsible party, emergency contact
- **Medical history** — conditions, medications, allergies, pregnancy, smoking. This is
  clinically load-bearing in dentistry: anticoagulants, bisphosphonates (MRONJ risk),
  diabetes (healing/perio), joint replacements and cardiac conditions (antibiotic
  prophylaxis decisions), latex allergy
- Dental history and chief complaint
- Insurance: carrier, subscriber, member ID, group number, employer, plus a photo of the card
- **HIPAA Notice of Privacy Practices** acknowledgment
- **Consent to treat** and financial policy agreement
- Photo ID and card images

Completed forms sync into the PMS as structured fields plus scanned documents. Paper
still exists in plenty of offices.

### 4.2 Identity and the family/account model

Dental PMSs are built around a **family or account** unit, not a lone patient: a
responsible party (guarantor) with dependents, one shared ledger, one statement. This
matters because a child's treatment appears on a parent's account, and the child may be
covered by two plans (both parents), triggering coordination of benefits.

There is no dental-specific national patient identifier. Deduplication is
last-name/DOB/phone matching inside a single practice's database, and a manual merge when
duplicates are found. There is **no cross-practice MPI**: if a patient moves to a new
dentist, their record does not follow. Records transfer by signed release, then fax, PDF,
CD, or a portal — imaging especially. Interoperability in dentistry is genuinely worse
than in medicine.

### 4.3 What the record contains

| Component | Format | Where it lives |
|---|---|---|
| Demographics, insurance, ledger | Structured DB rows | PMS |
| Medical/dental history | Structured + free text | PMS |
| **Odontogram** | Per-tooth, per-surface graphical chart with color-coded existing / planned / completed states | PMS clinical module |
| **Periodontal chart** | Up to **168 probing sites across 28 teeth** — probing depth, recession, bleeding on probing, furcation, mobility, plaque. A full-mouth chart takes **8–12 minutes** of continuous measure-and-record | PMS perio module |
| Clinical notes | Templated + narrative, per procedure and per visit | PMS |
| Radiographs | Bitewings, periapicals, panoramic, CBCT (DICOM) | Imaging software, linked by patient ID |
| Intraoral photos, scans | JPEG; STL/PLY for digital impressions | Imaging / scanner software |
| Signed forms, consents, correspondence, EOBs | Scanned PDF/image | PMS document center |
| Lab prescriptions and case tracking | Structured + lab portal | PMS + lab portal |

### 4.4 Storage, security, retention

- **HIPAA** requires encryption of ePHI in transit and at rest, access controls, audit
  logging, and a documented backup/recovery plan. The office manager is usually the
  designated Privacy/Security Officer.
- **Retention:** HIPAA requires certain documentation for at least **6 years**; state
  dental-record retention laws often require longer, and for minors typically some years
  past the age of majority. Practices generally retain records far longer than the minimum
  because of malpractice exposure.
- **Backup:** the **3-2-1** rule (three copies, two media types, one offsite), with
  immutable or air-gapped copies specifically because dental practices are a favored
  ransomware target — a small office with a single on-prem server, a flat network, and a
  backup drive plugged into that same server is the classic victim profile.
- Cloud PMSs (Curve, Denticon, Ascend, CareStack) move this burden to the vendor's BAA;
  server-based practices (Dentrix, Eaglesoft) own it themselves, which is a major driver of
  cloud migration.

**→ Repo delta.** `src/agents/patient/` models demographics intake, history fetch,
identity matching, an MPI-conflict human gate, history reconciliation, consent
presentation, and consent signature — a reasonable shape. But the **family/guarantor
account model is absent**, and it's the unit the whole ledger and statement side depends
on. The MPI-conflict gate is more sophisticated than reality (there is no cross-practice
MPI to conflict with); the realistic version is intra-practice duplicate detection. The
**odontogram and perio chart — the two most characteristically dental data
structures — are not modeled at all**, and the treatment plan builder invents a tooth
number by hashing (`treatment_plan_builder.py::_tooth_for`) rather than reading a chart.

**Sources:** [Overjet: periodontal chart guide](https://www.overjet.com/blog/periodontal-chart) ·
[Curve: hygienist workflow](https://www.curvedental.com/dental-blog/dental-osha-compliance-guide) ·
[Dentrix Ascend clinical charting](https://www.dentrixascend.com/features/clinical) ·
[EKIM IT: dental record retention](https://ekimit.com/how-long-dental-practices-keep-patient-records/) ·
[Accountable HQ: HIPAA-compliant backup](https://www.accountablehq.com/post/data-backup-best-practices-for-dental-offices-a-hipaa-compliant-ransomware-ready-guide)

---

## 5. Domain 3 — The clinical visit, chairside

### 5.1 A hygiene visit (the most common appointment type)

1. **Assistant or hygienist seats the patient**, confirms and updates medical history and
   medication list, takes blood pressure in many offices.
2. **Radiographs** per the office's interval protocol and the patient's caries risk —
   bitewings typically annually, full-mouth series or pano every 3–5 years. The assistant
   or hygienist exposes them; they appear in the imaging software within seconds.
3. **Hygienist performs the prophylaxis** — scaling, polishing, flossing, fluoride —
   while charting. **Perio charting** happens here; increasingly by voice dictation so the
   hygienist doesn't need a second person to record.
4. **Hygienist flags findings**: bleeding sites, pocket depths ≥4mm, suspicious lesions,
   fractured restorations, recession, calculus, oral-cancer-screening findings.
5. **The doctor exam ("doctor check").** The dentist comes into the operatory, reviews the
   hygienist's findings and the new radiographs, examines, and **diagnoses**. This handoff
   is the pivotal clinical moment of the visit — the hygienist gathers, the dentist decides.
6. **The dentist proposes treatment** verbally to the patient and enters planned procedures
   into the odontogram.
7. Clinical notes are written — templated, increasingly with ambient AI note generation.

### 5.2 A restorative / treatment visit

1. Assistant seats and preps, reviews the plan, sets out instruments.
2. Dentist confirms the tooth and procedure, administers local anesthetic.
3. Procedure performed (assistant chairside throughout). For a crown: prep, digital scan
   or impression, temporary crown, lab prescription.
4. Post-op instructions given, usually by the assistant.
5. **Prescriptions written if needed** (§9).
6. Dentist finalizes the note and marks the procedure **complete** in the chart. This
   completion event is what generates the charge — nothing is billable until the dentist
   marks it done.
7. Next visit scheduled at checkout (crown seat in 2–3 weeks).

### 5.3 Diagnosis → procedure coding

Dentistry codes **procedures**, not diagnoses, for billing. The billing code set is
**CDT** (Current Dental Terminology), maintained by the ADA, updated every January 1.

**CDT 2026** (effective 2026-01-01) contains **60 changes: 31 additions, 6 deletions, 14
revisions, 9 editorial actions.** Notable: a new code for cracked-tooth testing across
multiple teeth; two new codes for backup dentures (maxillary and mandibular); a new code
for cleaning and inspecting an existing occlusal guard. Deletions include **D1352**
(preventive resin restoration), tied to a descriptor change on **D2391** (posterior
composite, one surface). Payer policies update in lockstep on January 1 — meaning every
practice's fee schedule, estimate logic, and claim scrubbing needs an annual code review.

ICD-10-CM diagnosis codes are **optional on the dental claim** (the ADA form has boxes for
up to four) and are largely ignored by dental payers — but they become **mandatory** on the
medical cross-coding path (§7.7).

Common CDT codes in a general practice: D0120 periodic exam · D0150 comprehensive exam ·
D0210 full-mouth series · D0274 four bitewings · D0330 pano · D1110 adult prophy ·
D1206 fluoride varnish · D2391/D2392 posterior composite · D2740 porcelain/ceramic crown ·
D2950 core buildup · D3310/D3330 anterior/molar root canal · D4341/D4342 SRP per quadrant ·
D4910 perio maintenance · D7140 simple extraction · D7210 surgical extraction ·
D7953 bone graft · D6010 implant placement · D9110 palliative emergency treatment.

### 5.4 Who may do what — the hard legal boundaries

- **Only the dentist diagnoses.** A hygienist may identify and document findings; they may
  not diagnose or prescribe.
- **Only the dentist prescribes.** Staff may transmit at the dentist's direction, but the
  clinical decision and signature are the dentist's, under their DEA registration for
  controlled substances.
- **Only the dentist may sign the clinical note** as the treating provider.
- **Scope of practice for assistants and hygienists is state-specific** and varies widely
  (expanded-function assistants placing restorations, hygienists working under general vs
  direct supervision, hygienists in some states practicing independently).

**→ Repo delta.** `src/agents/clinical/` is the strongest-modeled domain: symptom
recording, diagnosis suggestion, a **diagnosis sign-off gate**, ICD-10 coding, a phased
treatment plan, a **dentist plan-review gate**, cost estimation, a **patient consent gate**,
prescription drafting, interaction and allergy checks, procedure documentation, EPCS
signing, and an EHR write. The gate placement is genuinely right — separating diagnosis
sign-off from plan review from patient consent matches how the real decisions split. Gaps:
(a) **no hygienist role and no hygienist→dentist handoff**, which is the actual clinical
pivot in the most common visit type; (b) **no radiographs** anywhere in the pipeline,
despite imaging being both the diagnostic basis and the thing payers demand as claim
evidence; (c) `procedure_documentor` records what was performed, but there's no notion of
a *completion event* being what makes a charge billable; (d) ICD-10 is treated as central,
when in dental billing it's optional and mostly ignored — CDT is the code that matters.

**Sources:** [ADA: new CDT codes for 2026](https://adanews.ada.org/ada-news/2025/september/new-cdt-codes-you-should-know-for-2026/) ·
[ADA: deleted CDT codes for 2026](https://adanews.ada.org/ada-news/2025/december/deleted-cdt-codes-you-should-know-for-2026/) ·
[ADA: revised CDT codes for 2026](https://adanews.ada.org/ada-news/2025/november/revised-cdt-codes-you-should-know-for-2026/) ·
[Delta Dental of Kansas: CDT 2026 changes](https://deltadentalks.com/uploads/media/DDKS_CDT_2026_Code_Changes.pdf) ·
[ADCA: 2026 dental procedure code guide](https://www.adcaonline.org/comprehensive-guide-to-dental-procedure-codes-2026-understanding-vital-updates-and-implementation-strategies/) ·
[Overjet: perio charting](https://www.overjet.com/blog/periodontal-chart)

---

## 6. Domain 4 — Treatment planning and the financial conversation

This is the step the user's question calls "how the bill is prepared," and it happens
**before** treatment, **before** the insurer sees anything.

### 6.1 Building the plan

The dentist enters planned procedures against specific teeth in the odontogram. The PMS
generates a treatment plan from the chart with each procedure linked to a tooth or
condition. Plans are **phased** because a single problem usually takes multiple visits and
sometimes healing time in between:

```
Phase 0  Emergency / palliative     — stop the pain now (D9110, pulpal debridement)
Phase 1  Disease control            — caries removal, SRP, extractions
Phase 2  Surgical                   — perio surgery, grafts, implant placement
Phase 3  Restorative / definitive   — crowns, bridges, implant crowns, dentures
Phase 4  Maintenance                — perio maintenance, recall
```

Example: tooth #19 with a periapical abscess → root canal (D3330) now, core buildup
(D2950) and crown (D2740) in 3–4 weeks once it settles. Two visits, two phases, one
problem.

### 6.2 Computing the estimate

For each planned procedure the PMS calculates:

```
office fee (or contracted allowed amount if in-network)
  − estimated insurance payment
      = allowed amount × the plan's category coverage %
        adjusted for: remaining annual maximum
                      remaining deductible
                      frequency limitations
                      waiting periods
                      LEAT / downgrade clauses
                      missing-tooth clause
                      COB if there's a second plan
  = ESTIMATED PATIENT PORTION
```

The benefit-design rules that make dental estimating hard:

| Rule | Effect |
|---|---|
| **Annual maximum** | A hard cap, commonly $1,000–$2,000/yr — roughly one crown. Unlike medical out-of-pocket maximums, this caps what the *plan* pays, not what the *patient* pays. Once hit, the patient owes 100% of everything else that year. This is the single most consequential number in dental estimating |
| **Category coverage %** | Classic split: preventive 100% / basic 80% / major 50%. Which category a code falls in is plan-specific and occasionally surprising |
| **Deductible** | Usually $50–$100, often waived for preventive |
| **Waiting periods** | 6–12 months on basic, 12–24 on major, for new enrollees |
| **Frequency limitations** | 2 cleanings per year, bitewings once per year, a crown on the same tooth once per 5–7 years |
| **LEAT / alternate benefit ("downgrade")** | When multiple acceptable treatments exist, the plan pays only for the cheapest one and the patient owes the difference. Canonical case: a posterior composite filling downgraded to the amalgam fee; also a crown downgraded to a filling, or an implant downgraded to a bridge or partial |
| **Missing tooth clause** | The plan won't pay to replace a tooth that was already missing before coverage started |
| **COB with a second plan** | Standard COB lets the secondary pay up to 100% of the covered service. **Non-duplication** COB pays nothing if the primary already paid as much as the secondary would have. Total from all sources never exceeds 100% of charges. Dual coverage does *not* double frequency limits |

Estimates are estimates. Even with a verified breakdown, the office is guessing at the
payer's adjudication.

### 6.3 Presenting it — the treatment coordinator's job

The dentist rarely discusses money. The **treatment coordinator** takes the patient to a
consult room and presents:

- What's wrong, in plain language, usually with the patient's own radiographs and intraoral
  photos on screen
- The recommended plan, phased, with a visit sequence
- Total fee, estimated insurance, **estimated patient portion per visit**
- Options: do everything, do phase 1 now, do the LEAT alternative, or decline
- Payment: pay today, card on file, in-house payment plan, or third-party financing
  approved at chairside in about a minute

The patient then **consents to specific line items** — commonly accepting part of a plan
and deferring the rest. Accepted-but-unscheduled treatment becomes a tracked backlog
("unscheduled treatment"), which analytics tools surface as the practice's largest
recoverable revenue pool.

### 6.4 Predetermination, when it's used

For expensive or judgment-dependent work, the office sends a **predetermination** instead
of proceeding: the same 837D claim structure, marked as a pre-treatment estimate, with
radiographs, perio charts, and a narrative attached. It comes back in roughly the same
time as a claim with the payer's estimate of coverage. The patient waits. Then treatment is
scheduled and the real claim goes later.

**→ Repo delta.** This is the domain the repo models *best* relative to typical demos —
`treatment_plan_builder` produces phased, per-tooth, CDT-coded line items;
`treatment_plan_review` is a dentist gate; `treatment_plan_consent` is a patient gate with
per-line-item decline; `treatment_cost_estimator` and `bill_splitter` share one
`adjudicate()` function so estimate and actual can't drift. That last choice is
genuinely correct engineering. What's missing is the benefit-design rules that make dental
estimating *dental*: **annual maximum tracking** (the sandbox has `annual_max_cents` and
`annual_max_used_cents` in `Coverage` but nothing consumes them), **LEAT/downgrade**,
**frequency limitations**, **waiting periods**, and the **missing-tooth clause**. Also
missing: the treatment coordinator as a distinct actor, and the "accepted but unscheduled"
state — the repo's consent gate is all-or-per-item within one encounter, with no backlog.

**Sources:** [ADA: LEAT clause](https://www.ada.org/resources/practice/dental-insurance/least-expensive-alternative-treatment-clause) ·
[ADA LEAT guidance PDF](https://www.ada.org/-/media/project/ada-organization/ada/ada-org/files/resources/practice/dental-insurance/least_expensive_alternative_treatment_clause.pdf) ·
[ADA: coordination of benefits](https://www.ada.org/resources/practice/dental-insurance/dental-plans-coordination-of-benefits) ·
[ADA guidance on COB](https://www.ada.org/resources/practice/dental-insurance/ada-guidance-on-coordination-of-benefits) ·
[Delta Dental: dual coverage](https://www.deltadentalnj.com/tools-and-resources/plan-information/dual-coverage) ·
[MouthHealthy: two dental plans](https://www.mouthhealthy.org/dental-care/if-you-have-two-dental-plans) ·
[Stedi: predetermination of benefits](https://www.stedi.com/blog/what-is-predetermination-of-benefits-for-dental-services) ·
[ADA: pre-authorizations](https://www.ada.org/resources/practice/dental-insurance/pre-authorizations) ·
[Dental Claim Support: predetermination vs preauthorization](https://www.dentalclaimsupport.com/blog/dental-predetermination-and-preauthorizations)

---

## 7. Domain 5 — Insurance: claim to remittance

### 7.1 Claim creation

Triggered by the dentist marking procedures **complete**. The insurance coordinator (or an
outsourced biller logged into the PMS) reviews and submits, usually as a batch at end of day.

The claim carries: subscriber and patient identifiers, employer/group, the billing dentist
and **treating dentist NPIs**, practice TIN, place of service, and per procedure — date of
service, **CDT code**, **tooth number** or quadrant/arch, surface, fee, and any prosthesis
replacement dates. Optional ICD-10 boxes usually left blank.

The paper form is the ADA **J430D**; the electronic equivalent is X12 **837D** (HIPAA
5010), which every payer publishes a companion guide for.

### 7.2 Attachments — the dental-specific step

Dental payers adjudicate on **visual evidence** far more than medical payers. A crown, SRP,
extraction, perio surgery, or implant claim generally needs supporting documentation:

- Pre-op periapical or bitewing radiographs
- Post-op radiographs for endodontics
- Full perio charting for SRP (probing depths justifying the diagnosis)
- Intraoral photographs
- A **narrative** from the dentist explaining what the radiograph can't show

These are uploaded to **NEA FastAttach** (or a native clearinghouse attachment service),
which returns an **attachment control number** referenced in the 837D's **PWK segment**
(e.g. `NEA#A12345678`). The payer pulls the images when adjudicating. Electronic
attachments shorten adjudication by roughly **3–7 days** versus fax or mail.

### 7.3 Transport and scrubbing

The claim goes to a **clearinghouse**, which validates it against payer-specific rules
before the payer sees it — missing fields, invalid codes, eligibility mismatches, tooth
numbers that don't make sense for the code. Claims failing scrub are **rejected back to the
office within minutes to hours**, which is a different and much better failure than a payer
denial: nothing was adjudicated, so the office fixes and resubmits with no appeal needed.

Electronic claims typically process in **7–14 days**; paper claims mailed to the payer can
take **30+ days**.

### 7.4 Adjudication at the payer

1. **Auto-adjudication.** Most clean claims are processed entirely by rules engines. At
   Delta Dental, auto-adjudicated claims average **under 3 business days**.
2. **Claims examiner review** for anything the engine kicks out.
3. **Clinical review** for procedures with clinical criteria. This is a real human chain:
   **dental case management staff** (licensed hygienists and assistants) do first-pass
   review, supervised by a **dental director**, with **general and specialty dental
   consultants** (licensed dentists) making the clinical calls. A consultant reviewing a
   crown claim, for instance, looks at the pre-op radiograph to judge whether enough tooth
   structure was lost that a direct filling would not have been adequate — a contractual
   criterion, not a matter of the treating dentist's opinion. Consultants explicitly cannot
   see the patient, which is why the narrative matters.
4. **Outcome per line item:** paid as submitted · paid at a reduced/downgraded amount ·
   applied to deductible · applied against the annual maximum · denied · pended for more
   information.

### 7.5 The remittance — where the truth arrives

The payer sends money (EFT or check) plus an **X12 835 Electronic Remittance Advice**,
which is the machine-readable EOB. Per claim and per line it reports:

- **Billed** amount
- **Allowed** amount (the contracted rate)
- **Paid** amount
- **Patient responsibility**
- **Adjustments** with **CARC** (Claim Adjustment Reason Code) and **RARC** (Remark Code)
  explaining every dollar of difference. Carriers publish policy-to-CARC/RARC mappings.

Key adjustment types the office must handle distinctly:

| Adjustment | Meaning | Accounting treatment |
|---|---|---|
| **Contractual write-off** (CARC 45) | Billed fee exceeded the contracted allowed amount | Written off. **Not billable to an in-network patient** — billing it is a contract violation |
| **Deductible** (CARC 1) | Applied to the patient's deductible | Patient owes |
| **Coinsurance** (CARC 2) | The patient's percentage share | Patient owes |
| **Copay** (CARC 3) | Fixed copay | Patient owes |
| **Downgrade / alternate benefit** | Paid at the LEAT fee | Patient owes the difference (if disclosed and consented) |
| **Annual maximum exhausted** | Benefit used up | Patient owes 100% |
| **Denial** | Not covered / not medically necessary / frequency exceeded / missing info | Appeal, write off, or bill the patient depending on cause and contract |

The insurance coordinator **posts the ERA** — the PMS auto-populates paid amounts against
each claim line, applies the write-offs, and finalizes the payment with the check/EFT
number. Practices moving from paper EOBs to ERAs cut posting time by roughly **60–75%**.
Critically: **$0 paid can be a correct adjudication** — if the patient's deductible or
annual maximum absorbed the whole allowed amount, the claim was processed properly and the
balance simply shifts to the patient. That is not a denial and must not be handled as one.

### 7.6 Denials, appeals, AR

The insurance coordinator or RCM vendor works an **AR aging report** bucketed by
30/60/90/120+ days:

- Chase unpaid claims with an X12 **276** status inquiry or a phone call
- **Appeal** denials with a stronger narrative, better radiographs, or a peer-to-peer
  request to the payer's dental consultant
- Correct and resubmit rejected claims
- Write off what's genuinely uncollectible
- Transfer the remaining balance to the patient

Common dental denial causes: missing or inadequate attachments, frequency limitation
exceeded, waiting period not met, missing tooth clause, downgrade applied, wrong tooth
number, coverage terminated, COB not sent to the primary first, and timely-filing limits
blown.

### 7.7 The medical cross-coding path

Some dental work is properly billed to the patient's **medical** plan, and this is where
real prior authorization lives:

| Procedure | Medical coding | Note |
|---|---|---|
| CBCT / cone beam imaging | **CPT 70486** (maxillofacial CT) with an ICD-10 such as **K01.1** (impacted teeth) | Medical reimburses CBCT substantially better than dental |
| Oral sleep apnea appliance | **HCPCS E0486** with **ICD-10 G47.33** (OSA) | Treated as medically necessary DME |
| Medically necessary oral surgery, biopsies, bone grafts | CPT + ICD-10 | Trauma, pathology, infection |
| TMJ therapy | CPT + ICD-10 | Coverage varies widely |

Cross-coded claims use CPT/HCPCS and **mandatory** ICD-10, go on a CMS-1500 or 837P, face
stricter documentation standards, and **frequently require prior authorization** (X12 278).
Many dental offices simply don't do this because it's a different skill set — which is why
cross-coding services are a business.

**→ Repo delta.** `src/agents/insurance/` models eligibility, formulary, predetermination
submit + a review gate, claim build, claim submit, **remittance processing**, and payment
reconciliation — and `src/agents/billing/` reconciles against the ERA. Modeling both halves
(837 out, 835 back with CARC codes and a contractual write-off) is well above the usual
demo bar, and `SandboxClaims.get_remittance` correctly treats $0-paid-due-to-deductible as
`paid` rather than `denied`. The real gaps: (a) **attachments do not exist** — no
radiographs, no perio chart, no narrative, no PWK/NEA control number — and in dentistry
that's the single most common cause of denial, so it's the highest-value addition;
(b) **clearinghouse scrub-and-reject is missing**, collapsing two very different failure
modes (rejection vs denial) into one; (c) the **payer-side human chain** (case management →
consultant → dental director) isn't modeled, though `predetermination_review` gestures at
it; (d) the repo treats predetermination as a mandatory-ish gate triggered by a code list,
whereas it's voluntary and advisory; (e) **no medical cross-coding path**, which is
ironically where the repo's X12 278 prior-auth model would actually be accurate;
(f) **no AR aging, no timely filing, no 276/277 status inquiry**.

**Sources:** [ADA dental claim form](https://www.ada.org/publications/cdt/ada-dental-claim-form) ·
[Lassie: ADA claim form guide](https://www.lassie.ai/blog/ada-dental-claim-form-explained) ·
[Vyne FastAttach](https://vynedental.com/fastattach/) ·
[Ventus AI: NEA / PWK](https://www.ventus.ai/glossary/dental-claim-attachment-nea/) ·
[Open Dental: claim attachments](https://opendental.blog/feature-highlight-claim-attachments/) ·
[PracticeAlpha: dental clearinghouses](https://practicealpha.io/blog/dental-clearinghouses/) ·
[Delta Dental dentist FAQ: adjudication timing and review chain](https://www1.deltadentalins.com/faqs/dentists.html) ·
[Delta Dental: when to send X-rays](https://www.deltadentalins.com/dentists/guidance/when-to-send-x-rays.html) ·
[Delta Dental: CARC/RARC policy mapping](https://www1.deltadentalins.com/content/dam/ddins/en/pdf/dentists/policy-mapping-carc-rarc.pdf) ·
[Open Dental: ERA manual](https://www.opendental.com/manual/claimsera835.html) ·
[Open Dental: ERAs for high-volume practices](https://opendental.blog/eras-for-high-volume-practices/) ·
[ADA: claims processing delays](https://www.ada.org/resources/practice/dental-insurance/claims-processing-delays) ·
[Nierman: cross-coding dental to medical](https://niermanpm.com/blog/cross-code-dental-to-medical/) ·
[Implant Practice US: billing medical for CBCT](https://implantpracticeus.com/billing-medical-for-cone-beam-computed-tomography-cbct/) ·
[ADCA: medical-dental cross coding](https://www.adcaonline.org/medical-dental-cross-coding-guide-2025/)

---

## 8. Domain 6 — Billing the patient

### 8.1 What the patient is shown, and when

**At checkout, same day as treatment:** a walkout statement / receipt showing procedures
performed, the office fee, **estimated** insurance portion, **estimated** patient portion,
what they paid today, and any remaining estimated balance. The front desk or financial
coordinator collects the estimated patient portion right there — card, cash, HSA/FSA, card
on file, or financing.

**Weeks later, after the ERA posts:** the picture changes. Three outcomes:

| Outcome | What the patient receives |
|---|---|
| Estimate was accurate | Nothing, or a zero-balance statement |
| Insurance paid **less** than estimated | A **balance statement** for the difference. The most common source of patient complaints in dentistry |
| Insurance paid **more** than estimated | A **refund** — check, or credit against future treatment |

Separately, the payer mails the patient its own **EOB**, which is the same adjudication
from the other side. Patients routinely misread it as a bill; the office spends real time
explaining that it isn't.

### 8.2 What must and must not appear on the patient's bill

For an **in-network** provider:

```
office full fee                          $1,500   (informational only)
− contractual write-off (CARC 45)        −$300    NOT billable to the patient
= contracted allowed amount              $1,200
− insurance paid                         −$660
= patient responsibility                 $540     ← deductible + coinsurance
+ non-covered / downgrade difference     + $X     ← only if disclosed and consented
+ elective upgrades                      + $Y
= PATIENT BALANCE DUE
```

Billing the contractual write-off to an in-network patient is a **participating-provider
agreement violation**. Out-of-network changes this entirely — there's no contracted rate,
so the patient can be balance-billed the full difference, which is why network status is
the most financially consequential fact about a dental visit.

### 8.3 Collections and financing

- **Time-of-service collection** is the goal; practices measure the percentage of
  patient-portion collected at the chair
- **Statements** monthly, increasingly by text with a pay link rather than mail
- **In-house payment plans**, sometimes with card on file auto-charged
- **Third-party financing** — the patient's credit, not the practice's risk; the practice is
  paid upfront and pays a merchant fee. CareCredit (Synchrony) is the incumbent; Sunbit and
  Cherry compete on approval rate and soft credit pulls. Approval decisions happen in about
  a minute at chairside, which is why financing is now embedded directly in PMS treatment
  presentation
- **Collections agency** as a last resort after 90–120+ days, at real reputational cost

### 8.4 Sales tax

Professional dental services are not taxed. Some **retail/ancillary items** sold to
patients — electric toothbrushes, whitening kits, night guards in some jurisdictions —
may be, state-dependent. Prescriptions are generally exempt.

**→ Repo delta.** `src/agents/billing/` covers fee calculation, coverage coordination
(including COB stacks and dual-eligible), tax, bill splitting with cash-vs-insured options,
invoicing, a **patient payment-authorization gate**, payment processing, denial detection,
a **coding QA gate**, and a **denial/appeal gate**. `bill_splitter.py` correctly adjudicates
against the remittance's *allowed* amount and surfaces the contractual write-off separately,
which is the thing most implementations get wrong. What's missing is the **two-phase
reality**: the repo produces one bill inside a single encounter, whereas real dentistry
produces an *estimate-based collection at checkout* and then a *reconciled balance
statement or refund weeks later*. There is no refund path, no patient statement cycle, no
AR aging, and no in-network-vs-out-of-network distinction — and that last one changes
whether the write-off is billable at all.

**Sources:** [ADA: LEAT clause](https://www.ada.org/resources/practice/dental-insurance/least-expensive-alternative-treatment-clause) ·
[Teero: ERA vs EOB](https://www.teero.com/blog/era-vs-eob) ·
[DayDream: outsourced dental billing / RCM](https://www.daydream.dental/blog-post/outsource-dental-billing-complete-guide-to-revenue-cycle-management) ·
[Dentistry Billing Solutions: process](https://www.dentistrybillingsolutions.com/how-it-works) ·
[Cherry vs Sunbit](https://withcherry.com/blog/sunbit-dental) ·
[CareCredit/Sunbit comparison](https://withcherry.com/blog/sunbit-vs-carecredit)

---

## 9. Domain 7 — Prescriptions and the pharmacy

### 9.1 What dentists actually prescribe

A narrow formulary. Dentists write a small number of drug classes:

- **Antibiotics.** Amoxicillin dominates, then amoxicillin/clavulanate, then clindamycin
  for penicillin-allergic patients. (Percentages from a questionnaire study —
  amoxicillin 54.2%, amox/clav 24.5%, clindamycin 21.0% — are directional, not US claims
  data.) Used therapeutically for odontogenic infection and prophylactically before
  invasive procedures in specific cardiac and prosthetic-joint patients. Dentists write
  roughly **10% of all human antibiotic prescriptions worldwide**, and the CDC's position
  is that **up to 80% of pre-procedure antibiotic prophylaxis is unnecessary** — dental
  antibiotic stewardship is an active public-health issue.
- **Non-opioid analgesics.** Ibuprofen and acetaminophen, alone or combined — now the
  evidence-based first line for acute dental pain.
- **Opioids.** Hydrocodone/acetaminophen, oxycodone/acetaminophen, acetaminophen with
  codeine. Historically dentistry was a major source of first opioid exposure in
  adolescents; prescribing has fallen substantially and is now typically small quantities
  for short durations, if at all.
- **Antimicrobial rinses** — chlorhexidine gluconate 0.12%.
- **Topical fluoride, antifungals** (nystatin, clotrimazole for candidiasis), and
  **anxiolytics** for pre-op sedation (triazolam, diazepam — controlled).

### 9.2 The e-prescribing flow, precisely

1. **The dentist decides.** No one else can. Inside the PMS's embedded e-Rx module
   (DoseSpot, iCoreRx, Veradigm, DrFirst, NewCrop) they select drug, strength, form,
   quantity, sig, refills.
2. **Automated clinical checks fire** against the patient's medication list and allergies:
   drug–drug interactions, drug–allergy, duplicate therapy, dose range. The dentist can
   override with a reason.
3. **For controlled substances:** the dentist must check the **state PDMP** (mandatory in
   most states, generally accessible in-workflow via Bamboo Health's PMP Gateway, with
   multi-state data where available), then sign under **DEA EPCS** — which requires
   completed **identity proofing** and **two-factor authentication** at the moment of
   signing (a hard token, or a push to a registered phone). Per 21 CFR 1311. Staff cannot
   perform this step.
4. **The patient names their pharmacy.** The dentist's software looks it up in the
   Surescripts pharmacy directory by name/address and resolves it to an **NCPDP ID**.
5. **Transmission.** An NCPDP SCRIPT **`NewRx`** message goes over the **Surescripts**
   network to that pharmacy's dispensing system. Seconds. The related transaction set
   includes `RxChange` (pharmacist requests a change), `RxRenewal` (refill authorization
   request back to the dentist), `RxFill` (optional dispensing notification), `RxTransfer`,
   and `CancelRx`.
6. **At the pharmacy — a separate professional workflow the clinic has no view into:**
   - Technician enters/verifies the Rx
   - **Insurance adjudication against the PBM** — the patient's *pharmacy* benefit, with
     its own formulary, tier, copay, and prior-auth rules, entirely separate from the
     dental plan. Rejections here (not on formulary, needs PA, refill too soon) are
     resolved between pharmacy, PBM, and prescriber
   - **Pharmacist performs DUR** and applies independent professional judgment. They may
     call the dentist to question the choice, and they **may refuse to fill**
   - Filled, labeled, shelved
   - Controlled substances reported to the **state PDMP** by the pharmacy
7. **The patient picks it up**, gets pharmacist counseling, pays their pharmacy copay.
   Possibly tomorrow. Possibly never — primary non-adherence is real.

### 9.3 Mandates that matter

- **CMS:** since **2023-01-01**, all controlled-substance prescriptions under Medicare
  Part D must be transmitted electronically.
- **State e-prescribing mandates** apply to dentists as prescribers. California requires
  all Dental Board licensees with prescribing authority to transmit **both controlled and
  non-controlled** prescriptions electronically (effective January 2022), with limited
  exemptions. Many other states mandate EPCS for controlled substances specifically.
  Requirements are state-by-state and change.
- **PDMP check requirements** before prescribing controlled substances are state-specific
  in both trigger and frequency.

### 9.4 What does *not* happen

- The clinic does not "contact a nearby pharmacy" or pick one for the patient.
- Nothing is dispatched, couriered, or delivered by the clinic.
- The clinic has no visibility into stock, fill status, or pickup unless the pharmacy
  volunteers an `RxFill`.
- In-office dispensing exists but is uncommon in general dentistry and state-restricted.
- There is no "pharmacist verification" gate *inside the clinic's* workflow — the
  pharmacist's verification is a real and legally required step, but it happens in the
  pharmacy's system, hours or days later, and the clinic only learns of it if there's a
  problem.

**→ Repo delta.** `src/agents/pharmacy/` models order receipt, an allergy gate, DUR
screening, PDMP query, stock check, **pharmacist verification** as a human gate, dispensing,
and dispatch tracking with an `in_transit` status. Two structural mismatches: (a) the
pharmacy domain runs **synchronously inside the clinic's encounter**, whereas in reality it
is a *separate organization's asynchronous workflow* starting when the `NewRx` lands and
finishing whenever the patient shows up — the pharmacist-verification gate is correctly
identified as legally required (OBRA-90) but wrongly located inside the clinic's pipeline;
(b) `dispatch_tracker` with `in_transit`/tracking numbers models **mail-order delivery**,
not retail pickup, which is what dental prescriptions overwhelmingly are. Also missing:
**PBM adjudication** (a whole second insurer the repo doesn't have), and the `RxChange` /
`RxRenewal` / `CancelRx` transactions that make up much of the real message traffic.
`formulary_checker` living in the *insurance* domain is closer to right than it looks, but
the formulary that matters belongs to the PBM, not the dental payer.

**Sources:** [Surescripts: e-prescribing and the NCPDP transaction set](https://surescripts.com/what-we-do/e-prescribing) ·
[Nalashaa: how the eRx process works](https://blog.nalashaahealth.com/how-the-erx-process-works/) ·
[RXNT: state EPCS mandates](https://www.rxnt.com/epcs-mandates/) ·
[CDA: California e-prescribing mandate for dentists](https://www.cda.org/newsroom/dental-practice-licensing/electronic-prescribing-for-controlled-and-uncontrolled-substances-becomes-mandatory-in-california-in-january-2022/) ·
[Open Dental: state e-prescribing mandates](https://opendental.blog/ensure-youre-compliant-with-new-state-e-prescribing-mandates/) ·
[Open Dental: PDMP and e-prescribing](https://opendental.blog/e-prescribing-and-pdmp-in-open-dental/) ·
[DrFirst: EPCS and PDMP state requirements](https://drfirst.com/current-epcs-pdmp-compliance-state-requirements) ·
[AGD: mandated EPCS laws](https://www.agd.org/constituent/news/2020/08/10/don-t-panic-over-mandated-e-prescribing-of-controlled-substances-laws) ·
[CDC: antibiotic prescribing in dentistry](https://www.cdc.gov/antibiotic-use/media/pdfs/dental-fact-sheet-508.pdf) ·
[Antibiotic-prescribing habits in dentistry (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10886335/) ·
[NIDCR: opioids and dental pain](https://www.nidcr.nih.gov/health-info/opioids)

---

## 10. One real encounter, end to end

A patient with a broken molar needing a root canal and crown, in-network PPO, $1,500 annual
maximum, $50 deductible unmet, major services at 50%.

| When | What happens | Who | System |
|---|---|---|---|
| **Day −3** | Patient calls with pain. Front desk books an emergency exam tomorrow | Patient, front desk | PMS scheduler |
| **Day −3** | Digital forms texted; patient completes history and insurance | Patient | Forms platform → PMS |
| **Day −2** | 270 sent, 271 back in seconds. Coordinator calls the payer for the full breakdown: major 50%, $1,500 max, $1,290 remaining, $50 deductible unmet, crown frequency 5 yrs, composite downgrade in effect | Insurance coordinator | Clearinghouse + payer portal |
| **Day −1** | Automated 24h reminder; patient confirms by text | Patient | Comms platform |
| **Day 0, 9:00** | Check-in, forms verified, ID and card scanned | Front desk | PMS |
| **9:10** | Assistant seats patient, updates history, exposes PA of #19 | Assistant | Imaging |
| **9:20** | Dentist examines, reads the radiograph, **diagnoses** irreversible pulpitis with periapical involvement. Plans D3330 RCT, D2950 buildup, D2740 crown | Dentist | PMS chart |
| **9:35** | TC presents the plan: $2,400 total. Insurance ~$620 (after deductible, at 50%, capped by remaining max). Patient portion ~$1,780. Patient accepts, takes Cherry financing, approved in 60 seconds | TC, patient | PMS treatment planner, financing app |
| **10:00** | D9110 palliative treatment today for pain; RCT scheduled in 3 days | Dentist, front desk | PMS |
| **10:20** | Checkout. Patient pays estimated portion for today's visit; walkout statement printed | Front desk, patient | PMS ledger, terminal |
| **10:30** | Claim for D0140 + D9110 built and queued | Insurance coordinator | PMS claims |
| **Day 0, 18:00** | End-of-day batch: 837D to clearinghouse, scrubbed, forwarded | Coordinator | Clearinghouse |
| **Day 3** | RCT performed. Dentist writes amoxicillin 500mg TID ×7d + ibuprofen 600mg. Patient names their pharmacy. `NewRx` over Surescripts | Dentist, patient | e-Rx module |
| **Day 3, +2h** | Pharmacy tech enters it, adjudicates against the PBM, pharmacist does DUR and verifies, fills | Pharmacy tech, pharmacist | Pharmacy system, PBM |
| **Day 3, evening** | Patient picks up, pays a $10 pharmacy copay, gets counseling | Patient, pharmacist | — |
| **Day 3** | Claim for D3330 built. Pre-op and post-op radiographs uploaded to FastAttach; NEA# referenced in the 837D PWK segment | Coordinator | Attachment service |
| **Day 9** | ERA arrives for Day 0 claims: exam paid at 100%, palliative paid at 80%, contractual write-off applied (CARC 45), $50 deductible applied (CARC 1). Coordinator posts it | Coordinator | PMS ERA |
| **Day 14** | Crown prep. Digital scan sent to the lab; temporary placed | Dentist, assistant | Scanner, lab portal |
| **Day 17** | ERA for the RCT. Payer's consultant reviewed the radiographs and paid as submitted. Remaining annual max now $470 | Coordinator, payer consultant | PMS ERA |
| **Day 30** | Crown seated. Claim for D2740 + D2950 submitted with pre-op radiograph | Dentist, coordinator | PMS, clearinghouse |
| **Day 44** | ERA: crown paid $470 — **annual maximum exhausted**, remainder to patient. Estimate was $160 low | Coordinator | PMS ERA |
| **Day 45** | Balance statement texted to the patient for the $160 difference, with an explanation | Financial coordinator | Statements |
| **Day 45** | Payer mails the patient its own EOB; patient calls confused, thinking it's a second bill | Patient, front desk | — |
| **Day 60** | Patient's next hygiene visit pre-appointed; recall set for 6 months | Hygiene coordinator | PMS recall |
| **Day 210** | Automated recall campaign fires; patient rebooks | Comms platform | PMS |

---

## 11. Consolidated gap list for this repo

Ordered by how much the gap distorts the model, most first.

| # | Gap | Why it matters | Where it would go |
|---|---|---|---|
| 1 | **Two-phase billing** — estimate collected at checkout, then reconciled weeks later into a balance bill or refund | The repo produces one bill per encounter. This is the central financial mechanic of US dentistry and the source of most real AR pain | `billing/` — split `invoice_generator` into estimate vs final statement; add refund path |
| 2 | **Claim attachments** (radiographs, perio chart, PWK/NEA#) — *narrative + denial routing now DONE* | The #1 cause of dental claim denial. `clinical/claim_narrative_writer.py` generates the per-tooth narrative and names the radiographs/charting each procedure needs, and `shared/payer_outcomes.py` now routes a missing-attachment denial to a RESUBMISSION rather than an appeal. What remains is the imaging itself and the NEA attachment-control-number round trip | `insurance/claim_builder` carries `attachments_recommended`; still needs an `attachment_assembler` + imaging in `clinical/` |
| 3 | **Annual maximum consumption** | The single most consequential number in dental estimating. `Coverage` already carries `annual_max_cents`/`annual_max_used_cents` and nothing reads them | `shared/adjudication.py`, `bill_splitter`, `treatment_cost_estimator` |
| 4 | **LEAT / downgrade, frequency limits, waiting periods, missing-tooth clause** | These are what make dental benefit design distinct from medical | `shared/adjudication.py` + `Coverage` model |
| 5 | **Hygienist as an actor, and the hygienist→dentist handoff** | The clinical pivot of the most common appointment type is entirely absent | `clinical/` — new hygiene assessment step feeding `diagnosis_suggester` |
| 6 | **Odontogram + perio chart as data structures** | The two characteristically dental records. Currently tooth numbers are hash-generated | `shared/` new models; `integrations/` sandbox data |
| 7 | **Pharmacy as an asynchronous external organization** | Pharmacist verification is real and required, but happens in the pharmacy's system later — not as a gate in the clinic's encounter | Restructure `pharmacy/` as a post-encounter async flow |
| 8 | **In-network vs out-of-network** | Determines whether the contractual write-off is billable to the patient at all | `Coverage` + `bill_splitter` |
| 9 | **Clearinghouse scrub → rejection** (distinct from payer denial) | Two different failure modes with different remediation, currently collapsed into one | `insurance/claim_submitter` |
| 10 | **Pre-visit eligibility timing** | Verification happens days before the visit and gates accurate estimating; the repo runs it mid-encounter | Move/duplicate ahead of `scheduling` |
| 11 | **Family / guarantor account model** | The unit the ledger and statements are actually built on | `patient/`, `billing/` |
| 12 | **Appointment duration derived from procedure type; operatory/hygiene columns** | Slot selection is currently length- and resource-agnostic | `scheduling/availability_finder`, `SchedulePort` |
| 13 | **Medical cross-coding path** (CPT/HCPCS + mandatory ICD-10 + real X12 278 PA) | Ironically the one place the repo's prior-auth model would be accurate | New sub-flow off `insurance/` |
| 14 | **AR aging, timely filing, 276/277 claim status** | Where insurance coordinators actually spend their day | New `billing/ar_*` agents |
| 15 | **PBM as a second, separate payer** | The drug claim is adjudicated by a different insurer with a different formulary and copay | `pharmacy/`; move formulary semantics off the dental payer |
| 16 | **Accepted-but-unscheduled treatment backlog** | The largest recoverable revenue pool in a real practice; consent is not a one-shot event | `clinical/treatment_plan_consent` → persistent state |
| 17 | **Predetermination is voluntary and advisory** | The repo triggers it from a code list as a quasi-mandatory gate | `insurance/predetermination_submitter` condition |

Two things the repo already gets right that are worth protecting:

- **One shared `adjudicate()` for both the estimate and the actual remittance**
  (`shared/adjudication.py`) — so the pre-treatment estimate and the payer's ERA can only
  diverge when the underlying facts diverge. This is the correct structural answer to the
  #1 gap above, and it's already in place.
- **`$0 paid ≠ denied`** in `SandboxClaims.get_remittance` — a deductible or exhausted
  annual maximum absorbing the whole allowed amount is a correct adjudication, not a
  failure. Most implementations get this wrong.

---

## 12. Standards and identifiers quick reference

| Standard | Use in a dental practice |
|---|---|
| **CDT** (ADA) | The dental procedure code set. Updated every Jan 1. CDT 2026: 31 added, 6 deleted, 14 revised, 9 editorial |
| **ADA J430D** | The paper dental claim form |
| **X12 837D** | Electronic dental claim (HIPAA 5010) |
| **X12 835** | Electronic remittance advice (ERA) |
| **X12 270/271** | Eligibility inquiry / response |
| **X12 276/277** | Claim status inquiry / response |
| **X12 278** | Prior authorization — *medical* path only in dentistry |
| **X12 834 / 820** | Enrollment / premium payment (payer-side, not the practice's concern) |
| **CARC / RARC** | Claim adjustment reason and remark codes on the 835 |
| **PWK segment + NEA#** | Attachment reference on the 837D |
| **CPT / HCPCS / ICD-10-CM** | Medical cross-coding (CPT 70486 CBCT, HCPCS E0486 sleep appliance, ICD-10 G47.33 OSA, K01.1 impacted teeth) |
| **NCPDP SCRIPT** | E-prescribing message set: NewRx, RxChange, RxRenewal, RxFill, RxTransfer, CancelRx |
| **DEA EPCS / 21 CFR 1311** | Controlled-substance e-signing: identity proofing + two-factor |
| **NPI** | Provider identifier (billing entity and treating dentist) |
| **NCPDP ID** | Pharmacy identifier |
| **DICOM** | 3D/CBCT imaging interchange |
| **HIPAA** | Privacy, security, 6-year documentation retention floor |
| **FHIR R4** | Widely used in medical interoperability; **rare in dental PMS**. Notable, given this repo's EHR port is FHIR-shaped |
