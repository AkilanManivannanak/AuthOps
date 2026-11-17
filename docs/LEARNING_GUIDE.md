# Learning guide: prior authorization AI operations

This guide teaches the domain and the system well enough to explain every design choice in an
interview. Work through it in order. Each section ends with drills. Answers are at the bottom.

---

## Part 1. The domain in 15 minutes

**Prior authorization (PA).** Before certain services, the payor (insurer) must approve them or
the claim will be denied. The provider sends a request with clinical documentation. The payor
approves, partially approves (fewer units or a shorter period) or denies.

**The lifecycle**
1. Intake: patient, insurance and the ordered service arrive (EHR, referral, fax).
2. Benefit check / eligibility: is the member active, and does this service need PA?
3. Documentation: treatment plan, referral, notes. Missing pieces cause most avoidable denials.
4. Submission: payor portal (most volume), fax, phone or, from 2027, a FHIR API.
5. Follow-up: status checks until a determination letter arrives.
6. Determination letter: auth number, approved units, date range. This is what the
   extraction module reads.
7. Tracking: units used against units approved, and reauthorization before expiry.

**Codes you must know**
- **ICD-10-CM:** diagnosis codes. F84.0 autism, M54.50 low back pain, F41.1 generalized anxiety disorder.
- **CPT / HCPCS:** procedure codes. 97153 is ABA treatment by a technician, 97155 is protocol
  modification by a BCBA, 97110 is therapeutic exercise in PT, 90837 is a 60-minute psychotherapy session.
- **NPI:** 10-digit provider ID with a Luhn check digit (computed over "80840" + the first 9 digits).
- **Units:** billing increments. ABA units are often 15 minutes, so 20 hrs/week is 80 units/week.

**Payor types:** commercial, Medicaid managed care organizations (MCOs, often the strictest on
documentation), Medicare Advantage, federal plans.

**Silna's specialties:** ABA (autism therapy, very PA-heavy and reauthorized every few months),
physical therapy, behavioral health, ambulatory, post-acute. ABA and PT are high-frequency
reauthorization businesses, which is why automation pays off.

**CMS-0057-F:** finalized January 2024. Since January 1, 2026 impacted payors must decide urgent
requests in 72 hours and standard in 7 days, and publish PA metrics. By January 1, 2027 they must
run four FHIR APIs: Patient Access, Provider Access, Payer-to-Payer and Prior Authorization.
The Da Vinci implementation guides behind the PA API:
- **CRD** (Coverage Requirements Discovery): does this need PA?
- **DTR** (Documentation Templates and Rules): what documentation is required?
- **PAS** (Prior Authorization Support): submit a Claim with `use = preauthorization` and receive a ClaimResponse.

Drills:
1. Why is ABA a good first market for PA automation?
2. A letter says "Approved Units: 120, Effective 12/01/2026 through 02/28/2027". Which fields does tracking need from it?
3. Why won't the 2027 FHIR rule make browser agents obsolete in 2027?

---

## Part 2. How AuthOps works (read the code in this order)

1. `authops/synth/generate.py`: fictional payors and cases. Note `injected_gaps` and the
   hidden Keystone PT policy in `payor_decision`. That is requirements drift on purpose.
2. `authops/synth/render.py`: three letter templates and three image conditions. Look at a fax PNG in `data/docs/`.
3. `authops/docintel/ocr.py` then `extract.py`: OCR with word confidence; rules baseline;
   Claude extractor with evidence quotes, chunk then synthesize, groundedness cap and abstention.
4. `authops/docintel/evaluate.py`: precision vs accuracy vs silent error. Learn these definitions cold.
5. `authops/validation/rules.py`: default vs custom rules; why a non-YES/NO answer is not a pass.
6. `authops/portals/app.py`: every failure mode Silna wrote about, as a sandbox.
7. `authops/agent/`: observe (frames, occlusion), tools (semantic targets, calendar, TOTP),
   runtime (guards, classification, loop detection, verification), policy (playbook vs Claude).
8. `authops/ops/`: smoothness score, experiments and QA ramp, QA reviewer, SQLite store.
9. `authops/channels/router.py` and `authops/phone/ivr.py`.

Drills:
4. Why does `type_credential` exist instead of letting the model type the password?
5. What does the runtime do when Summit returns a 503 on submit, and why not retry forever?
6. Why is "precision when answered" a different number from "accuracy", and which one decides auto-submit?

---

## Part 3. Hands-on exercises (do these yourself, then talk about them)

1. **Add a portal.** Copy `northwind` into a fourth portal with one new quirk (for example, a
   CAPTCHA-like "type the code shown" step, or a units field capped at 3 digits). Write its
   `.yaml` and `.md` playbooks. Measure verified submit rate before and after your playbook fix.
2. **Write a custom rule.** Add "Does the plan include a discharge or transition plan?" for one
   payor. Run with an API key and look at how many cases the rule fails and whether it agrees with you.
3. **Break and fix extraction.** Add a fourth letter template with a two-column layout. Watch the
   rules baseline fail, then compare the Claude extractor. Report it as a slice in the table.
4. **Tune the ramp.** Change `QARamp(window=6)` to 12. Explain the trade-off (slower ramp, fewer false promotions).
5. **SQL.** Answer from `reports/authops.db`: which tool fails most often? Which portal has the
   most retries per run? Queries are in the README.

---

## Part 4. Interview talk track

**60-second pitch.** "I rebuilt a small version of the system behind prior-auth agents from your
engineering blog, against fictional payors. Documents go through OCR and extraction with
per-field confidence and abstention, then a rules engine that catches denials before submission.
Ready cases are routed FHIR first, then a browser agent, then a phone agent. The browser agent runs
against three sandbox portals I built with the failure modes your AI Ops team described: pop-ups,
iframes, calendars, conditional forms, TOTP, session kicks and lockouts. Every run gets a
smoothness score, QA review and an experiment arm, and the QA share ramps down only while
metrics hold. The numbers are in the report, including what doesn't work yet."

**Questions to expect, and the honest answer shape**
- *How do you know the agent generalizes?* "I don't from the playbook arm: I wrote both the portals
  and the playbooks. The LLM arm is the generalization test, and the ablations show which controls
  carry the result. On a real portal I would start in a sandbox with 100% QA."
- *What is the first metric you'd build for a new portal?* "Verified submit rate with QA-audited
  silent errors, then smoothness, then cost and duration per auth."
- *An agent's success rate dropped from 92% to 70% overnight. What do you do?* "Group failures by
  error class from the step table, open recordings for the top class, check whether the portal
  changed (new modal, new field) versus a model or credential problem, then fix the playbook or tool,
  backtest in the sandbox and raise the QA share until the fix holds."
- *How would you choose between Haiku and a bigger model per portal?* "Weighted split on the same
  cases, compare verified submit rate, silent errors, duration and tokens. Promote the cheaper arm
  only if it is not worse on silent errors."

---

## Answers

1. High reauthorization frequency, strict documentation rules, small providers without PA staff, and denials that interrupt care for children.
2. Auth number, approved units, start and end date, CPT codes, member ID, decision (partial vs full).
3. Commercial plans are outside the rule, implementations will be late and uneven, drugs are out of scope, and portals and fax remain the fallback.
4. Credentials never enter a prompt or a log, and login is one atomic, testable action.
5. It classifies the page as transient, backs off, goes back and resubmits, up to 3 times, then fails with `transient_5xx`. Unbounded retries can create duplicate submissions or trip rate limits.
6. Accuracy counts abstentions as wrong; precision only scores what was filled. Auto-submit depends on precision on critical fields plus coverage: a field the model leaves blank is safe to send to a human, a wrong one is not.
