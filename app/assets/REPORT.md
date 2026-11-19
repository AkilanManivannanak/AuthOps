# AuthOps evaluation report

Generated 2026-11-19 00:29. 80 synthetic cases, fictional payors, no real PHI. LLM arms: on. Environment: Tesseract 5.5.4, Python 3.12.12, Darwin.

## 1. Document extraction

Document type classification accuracy: 96.3%

| Extractor | Field accuracy | Precision when answered | Coverage | Silent error | Docs fully correct | p50 latency |
|---|---|---|---|---|---|---|
| rules | 91.8% | 98.6% | 93.1% | 1.3% | 68.8% | 787 ms |
| claude:claude-haiku-4-5 | 95.9% | 97.8% | 98.0% | 2.1% | 78.7% | 4622 ms |

By image condition and template (first extractor):

| Slice | n fields | Accuracy | Precision | Coverage | Silent error |
|---|---|---|---|---|---|
| cond:clean | 567 | 96.3% | 99.6% | 96.6% | 0.4% |
| cond:fax | 546 | 84.8% | 96.5% | 87.9% | 3.1% |
| cond:scan | 567 | 94.0% | 99.4% | 94.5% | 0.5% |
| tmpl:a | 320 | 97.2% | 99.4% | 97.8% | 0.6% |
| tmpl:b | 310 | 94.5% | 98.0% | 96.5% | 1.9% |
| tmpl:c | 170 | 70.6% | 94.5% | 74.7% | 4.1% |
| tmpl:tp | 880 | 93.0% | 99.2% | 93.8% | 0.8% |
| type:approval_letter | 560 | 89.1% | 97.7% | 91.2% | 2.1% |
| type:denial_letter | 240 | 93.8% | 98.7% | 95.0% | 1.3% |
| type:treatment_plan | 880 | 93.0% | 99.2% | 93.8% | 0.8% |

Weakest fields:

| Field | Accuracy | Coverage | Silent error |
|---|---|---|---|
| provider_npi | 81.2% | 81.2% | 0.0% |
| auth_number | 81.2% | 86.3% | 5.0% |
| icd10_codes | 86.3% | 91.2% | 5.0% |
| member_id | 86.9% | 86.9% | 0.0% |
| signature_date | 87.5% | 87.5% | 0.0% |
| approved_units | 87.5% | 87.5% | 0.0% |

### Trained confidence calibration (held-out cases)

Logistic model on inference-time signals, trained on 949 fields, tested on 656 fields from unseen cases.

| Score | AUROC (correct vs wrong) | Silent error at same coverage | Precision at same coverage |
|---|---|---|---|
| Heuristic (OCR conf x validators) | 0.968 | 2.0% | 97.9% |
| Learned calibrator | 0.965 | 2.1% | 97.7% |

Coverage held at 93.8% (the heuristic's own answer rate).

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
| portal:keystone | 6 | 100.0% | 97.8 | 9.81s | 18 | 0 |
| arm:claude-haiku-4-5 | 15 | 100.0% | 98.1 | 16.71s | 20.3 | 0 |
| all | 34 | 100.0% | 98.0 | 2.96s | 20.1 | 0 |
| portal:summit | 13 | 100.0% | 96.8 | 4.4s | 25.4 | 0 |
| arm:playbook | 19 | 100.0% | 98.0 | 1.14s | 20 | 0 |
| portal:northwind | 15 | 100.0% | 99.2 | 0.74s | 16.4 | 0 |

Error classes: {}
Silent errors (auto-submitted with a major issue): 0
Portal chaos events: {'session_kick': 32, 'lockout': 1}
Credentials disabled by the pool: [('sfb-ops-c', 'auth_invalid')]

### QA ramp

- **keystone** final human-QA share 0.70
  - after 6 runs: success 1.00, smoothness 98, silent errors 0 -> QA share 1.00 -> 0.70
- **summit** final human-QA share 0.40
  - after 6 runs: success 1.00, smoothness 94, silent errors 0 -> QA share 1.00 -> 0.70
  - after 12 runs: success 1.00, smoothness 99, silent errors 0 -> QA share 0.70 -> 0.40
- **northwind** final human-QA share 0.40
  - after 6 runs: success 1.00, smoothness 100, silent errors 0 -> QA share 1.00 -> 0.70
  - after 12 runs: success 1.00, smoothness 99, silent errors 0 -> QA share 0.70 -> 0.40

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

## 5. LLM usage

501 calls, 506175 input / 125573 output tokens, ~$1.134
