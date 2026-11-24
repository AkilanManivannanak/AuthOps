# AuthOps evaluation report

Generated 2026-11-23 23:51. 80 synthetic cases, fictional payors, no real PHI. LLM arms: on. Environment: Tesseract 5.5.4, Python 3.12.12, Darwin.

## 1. Document extraction

Document type classification accuracy: 96.3%

| Extractor | Field accuracy | Precision when answered | Coverage | Silent error | Docs fully correct | p50 latency |
|---|---|---|---|---|---|---|
| rules | 95.8% | 99.5% | 96.3% | 0.5% | 75.6% | 761 ms |
| claude:claude-haiku-4-5 | 95.3% | 97.8% | 97.4% | 2.1% | 78.7% | 4579 ms |

By image condition and template (first extractor):

| Slice | n fields | Accuracy | Precision | Coverage | Silent error |
|---|---|---|---|---|---|
| cond:clean | 567 | 98.2% | 100.0% | 98.2% | 0.0% |
| cond:fax | 546 | 92.3% | 98.6% | 93.6% | 1.3% |
| cond:scan | 567 | 96.8% | 99.8% | 97.0% | 0.2% |
| tmpl:a | 320 | 98.4% | 99.7% | 98.8% | 0.3% |
| tmpl:b | 310 | 95.8% | 99.0% | 96.8% | 1.0% |
| tmpl:c | 170 | 85.3% | 99.3% | 85.9% | 0.6% |
| tmpl:tp | 880 | 96.9% | 99.6% | 97.3% | 0.3% |
| type:approval_letter | 560 | 93.9% | 99.2% | 94.6% | 0.7% |
| type:denial_letter | 240 | 96.3% | 99.6% | 96.7% | 0.4% |
| type:treatment_plan | 880 | 96.9% | 99.6% | 97.3% | 0.3% |

Weakest fields:

| Field | Accuracy | Coverage | Silent error |
|---|---|---|---|
| auth_number | 78.7% | 78.7% | 0.0% |
| requested_units | 90.0% | 90.0% | 0.0% |
| icd10_codes | 93.8% | 93.8% | 0.0% |
| member_id | 95.0% | 95.0% | 0.0% |
| end_date | 95.0% | 95.0% | 0.0% |
| patient_dob | 96.3% | 97.5% | 1.3% |

### Trained confidence calibration (held-out cases)

Logistic model on inference-time signals, trained on 949 fields, tested on 656 fields from unseen cases.

| Score | AUROC (correct vs wrong) | Silent error at same coverage | Precision at same coverage |
|---|---|---|---|
| Heuristic (OCR conf x validators) | 0.952 | 0.9% | 99.1% |
| Learned calibrator | 0.920 | 1.5% | 98.4% |

Coverage held at 96.5% (the heuristic's own answer rate).

## 2. Pre-submission validation (denial prevention)

- Payor denials in the simulated set: 24 of 80 cases
- Caught before submission: 24 (recall 100.0%, precision 100.0%)
- False blocks (would have been approved): 0
- Missed: 0 []
- Rule hits: {'units_within_payor_limit': 4, 'school_schedule_attached': 3, 'icd10_billable': 8, 'signature_present': 3, 'cpt_matches_specialty': 3, 'plan_not_expired': 3}

## 3. Browser agents

Routing of ready cases: {'portal': 34, 'fhir': 10, 'phone': 12}; held for documentation fixes: 24

| Slice | Runs | Verified submit rate | Mean smoothness | p50 duration | Mean steps | Runs with major QA issue |
|---|---|---|---|---|---|---|
| portal:keystone | 6 | 100.0% | 97.8 | 10.67s | 18 | 0 |
| arm:claude-haiku-4-5 | 15 | 100.0% | 98.0 | 18.35s | 20.5 | 0 |
| all | 34 | 100.0% | 98.0 | 3.04s | 20.2 | 0 |
| portal:summit | 13 | 100.0% | 96.7 | 4.45s | 25.7 | 0 |
| arm:playbook | 19 | 100.0% | 98.0 | 1.19s | 20 | 0 |
| portal:northwind | 15 | 100.0% | 99.2 | 0.76s | 16.4 | 0 |

Error classes: {}
Silent errors (auto-submitted with a major issue): 0
Portal chaos events: {'session_kick': 32, 'lockout': 1}
Credentials disabled by the pool: [('sfb-ops-c', 'auth_invalid')]

### QA ramp

- **keystone** final human-QA share 1.00
  - after 6 runs: success 1.00, smoothness 98, silent errors 0, clean-run lower bound 0.61 -> QA share 1.00 -> 1.00
- **summit** final human-QA share 0.70
  - after 6 runs: success 1.00, smoothness 94, silent errors 0, clean-run lower bound 0.61 -> QA share 1.00 -> 1.00
  - after 12 runs: success 1.00, smoothness 99, silent errors 0, clean-run lower bound 0.76 -> QA share 1.00 -> 0.70
- **northwind** final human-QA share 0.70
  - after 6 runs: success 1.00, smoothness 100, silent errors 0, clean-run lower bound 0.61 -> QA share 1.00 -> 1.00
  - after 12 runs: success 1.00, smoothness 99, silent errors 0, clean-run lower bound 0.76 -> QA share 1.00 -> 0.70

### Ablations

| Variant | Runs | Submitted | Lockouts | Error classes |
|---|---|---|---|---|
| overlay_guard_on | 8 | 8 | - | {} |
| overlay_guard_off | 8 | 2 | - | {'timeout': 5, 'playbook_gap': 1} |
| credential_threshold_2 | 9 | 9 | 0 | {} |
| no_credential_threshold | 9 | 8 | 1 | {'account_locked': 1} |

## 4. Other channels

- FHIR PA API (Da Vinci PAS shape): 10/10 submitted, p50 0.007s per request
- Phone agent (IVR, benefits + status): 24/24 calls completed, mean 5 turns, member-ID repeats after ASR noise: 0

## Uncertainty

Small pilots need intervals, so every headline comparison carries one.

- rules: field accuracy 95% CI [0.948, 0.967], whole-document CI [0.645, 0.783], silent-error CI [0.0024, 0.0094]
- claude:claude-haiku-4-5: field accuracy 95% CI [0.942, 0.962], whole-document CI [0.678, 0.811], silent-error CI [0.0155, 0.0295]
- rules vs claude:claude-haiku-4-5: field accuracy diff +0.005 (95% CI -0.006 to +0.021, documents resampled), McNemar p=0.3492 (41 fields right only under rules, 32 only under claude:claude-haiku-4-5)
- overlay_guard_on: 8/8 vs 2/8 submitted, Fisher exact p=0.007
- credential_threshold_2: 9/9 vs 8/9 submitted, Fisher exact p=1.0
- denial-prevention recall 95% CI [0.862, 1.0]

## 5. LLM usage

505 calls, 512824 input / 126042 output tokens, ~$1.143
