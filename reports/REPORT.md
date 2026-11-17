# AuthOps evaluation report

Generated 2026-11-17 14:42. 80 synthetic cases, fictional payors, no real PHI. LLM arms: off (offline run). Environment: Tesseract 5.3.4, Python 3.13.18, Linux.

## 1. Document extraction

Document type classification accuracy: 96.3%

| Extractor | Field accuracy | Precision when answered | Coverage | Silent error | Docs fully correct | p50 latency |
|---|---|---|---|---|---|---|
| rules | 91.6% | 98.5% | 93.0% | 1.4% | 66.2% | 760 ms |

By image condition and template (first extractor):

| Slice | n fields | Accuracy | Precision | Coverage | Silent error |
|---|---|---|---|---|---|
| cond:clean | 567 | 96.8% | 99.6% | 97.2% | 0.4% |
| cond:fax | 546 | 83.9% | 96.2% | 87.2% | 3.3% |
| cond:scan | 567 | 93.8% | 99.3% | 94.5% | 0.7% |
| tmpl:a | 320 | 96.6% | 98.7% | 97.8% | 1.3% |
| tmpl:b | 310 | 94.8% | 97.7% | 97.1% | 2.3% |
| tmpl:c | 170 | 70.0% | 94.4% | 74.1% | 4.1% |
| tmpl:tp | 880 | 92.8% | 99.3% | 93.5% | 0.7% |
| type:approval_letter | 560 | 89.1% | 97.3% | 91.6% | 2.5% |
| type:denial_letter | 240 | 92.9% | 98.2% | 94.6% | 1.7% |
| type:treatment_plan | 880 | 92.8% | 99.3% | 93.5% | 0.7% |

Weakest fields:

| Field | Accuracy | Coverage | Silent error |
|---|---|---|---|
| auth_number | 77.5% | 83.8% | 6.2% |
| provider_npi | 81.2% | 81.2% | 0.0% |
| icd10_codes | 86.3% | 91.2% | 5.0% |
| signature_date | 87.5% | 87.5% | 0.0% |
| member_id | 88.7% | 88.7% | 0.0% |
| requested_units | 88.7% | 88.7% | 0.0% |

### Trained confidence calibration (held-out cases)

Logistic model on inference-time signals, trained on 949 fields, tested on 656 fields from unseen cases.

| Score | AUROC (correct vs wrong) | Silent error at same coverage | Precision at same coverage |
|---|---|---|---|
| Heuristic (OCR conf x validators) | 0.977 | 2.3% | 97.5% |
| Learned calibrator | 0.963 | 2.3% | 97.5% |

Coverage held at 93.3% (the heuristic's own answer rate).

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
| portal:keystone | 6 | 100.0% | 98.0 | 3.55s | 16.7 | 0 |
| arm:playbook | 34 | 100.0% | 98.4 | 1.81s | 19.0 | 0 |
| all | 34 | 100.0% | 98.4 | 1.81s | 19.0 | 0 |
| portal:summit | 13 | 100.0% | 97.1 | 1.97s | 24.4 | 0 |
| portal:northwind | 15 | 100.0% | 99.6 | 1.1s | 15.2 | 0 |

Error classes: {}
Silent errors (auto-submitted with a major issue): 0
Portal chaos events: {'session_kick': 32, 'lockout': 1}
Credentials disabled by the pool: [('sfb-ops-c', 'auth_invalid')]

### QA ramp

- **keystone** final human-QA share 0.70
  - after 6 runs: success 1.00, smoothness 98, silent errors 0 -> QA share 1.00 -> 0.70
- **summit** final human-QA share 0.40
  - after 6 runs: success 1.00, smoothness 95, silent errors 0 -> QA share 1.00 -> 0.70
  - after 12 runs: success 1.00, smoothness 99, silent errors 0 -> QA share 0.70 -> 0.40
- **northwind** final human-QA share 0.40
  - after 6 runs: success 1.00, smoothness 100, silent errors 0 -> QA share 1.00 -> 0.70
  - after 12 runs: success 1.00, smoothness 100, silent errors 0 -> QA share 0.70 -> 0.40

### Ablations

| Variant | Runs | Submitted | Lockouts | Error classes |
|---|---|---|---|---|
| overlay_guard_on | 8 | 8 | - | {} |
| overlay_guard_off | 8 | 2 | - | {'timeout': 5, 'playbook_gap': 1} |
| credential_threshold_2 | 9 | 9 | 0 | {} |
| no_credential_threshold | 9 | 8 | 1 | {'account_locked': 1} |

## 4. Other channels

- FHIR PA API (Da Vinci PAS shape): 10/10 submitted, p50 0.013s per request
- Phone agent (IVR, benefits + status): 24/24 calls completed, mean 5 turns, member-ID repeats after ASR noise: 0

## 5. LLM usage

0 calls, 0 input / 0 output tokens, ~$0.0
