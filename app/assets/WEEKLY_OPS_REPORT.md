# AI Operations weekly report
_Generated 2026-11-21 from run artifacts. Synthetic patients and sandbox portals only._

## Headline

- **Submissions:** 34 agent runs, 100.0% verified against the payor confirmation, mean smoothness 98.0/100, 0 silent errors found in QA.
- **Denials prevented:** 24 of 24 predictable denials caught before submission, 0 clean requests blocked by mistake.
- **Document extraction:** 98.6% precision on fields filled, 1.3% silent error, 68.8% of documents with every critical field right.
- **Long charts:** the background document agent made 0 false passes vs 5 for a single call, and held 97.9% on 100+ page charts vs 85.1%.

## Portal rollout status

| Portal | Runs | Verified | Smoothness | Human QA share | Decision |
|---|---|---|---|---|---|
| keystone | 6 | 100.0% | 97.8 | 70% | lower QA share next week if metrics hold |
| summit | 13 | 100.0% | 96.8 | 40% | lower QA share next week if metrics hold |
| northwind | 15 | 100.0% | 99.2 | 40% | lower QA share next week if metrics hold |

## New portal configuration

- Auto-drafted playbooks reached a confirmation on 8 of 12 sandbox walks, including 3/3 on the held-out Lakeshore portal. Drafts reproduced 92.6% of hand-written field mappings with 0 wrong mappings.
- **Needs a specialist decision (keystone):** Is a school schedule attached?; Requested hours on school days.
- **Needs a specialist decision (summit):** Is the member currently admitted inpatient?; Is this a continuation of an existing authorization?; Prior authorization number.

## Payor policy changes detected

| Week | Payor | Specialty | Signal | Before | After | Proposed |
|---|---|---|---|---|---|---|
| 7 | HBL | physical therapy | Submitted treatment plan dates have expired. | 0.011 | 0.152 | `{"physical_therapy": {"custom_rules": ["Does the request meet this pay` |
| 8 | KCM | physical therapy | Physical therapy is limited to 20 visits per authorizat | 0.0 | 0.4 | `{"physical_therapy": {"max_units_per_request": 20}}` |
| 10 | HBL | physical therapy | days to decision | 3.5 | 7.5 | `{"physical_therapy": {"turnaround_p90_days": 9}}` |
| 12 | NWH | aba | Standardized assessment must be dated within 6 months o | 0.0 | 0.176 | `{"aba": {"custom_rules": ["Does the request meet this payor requiremen` |
| 15 | SFB | behavioral health | partial approvals at 16 units | 0.069 | 0.333 | `{"behavioral_health": {"recommend_max_units": 16}}` |

## Portal releases

- northwind: unchanged.
- keystone: unchanged.
- lakeshore: unchanged.

## Top issues and owners

1. Summit locked a credential 1 time; the pool disabled the stale one. Owner: ops, rotate the password with the payor.
2. Extraction: only 68.8% of documents are fully right. Weakest fields: provider_npi (81.2%), auth_number (81.2%), icd10_codes (86.3%). Owner: AI Ops, prompt backtest extract@v2.
3. Benefits calls: read-back cuts wrong fields from 85 to 9 per 120 calls; ship read-back to every phone workflow. Owner: AI Ops + phone engineering.
4. Coverage monitor: proactive checks cut denied revenue 91% vs reacting to denials in simulation; pilot weekly checks with one ABA customer. Owner: customer success.

## Prompt changes

- 2026-11-21 22:22: extract@v2 (22f5e9eed5b0) vs extract@v1 on golden set 99a562ac6488: accuracy 0.957 -> 0.952, silent error 0.032 -> 0.033. **Blocked**: overall accuracy fell 0.957 -> 0.952; silent errors rose 0.032 -> 0.033; critical field icd10_codes fell 0.933 -> 0.900; critical field signature_present fell 1.000 -> 0.967.

## Decisions needed

- Approve the next QA-share step for portals whose metrics held all week.
- Assign a specialist to answer the flagged clinical questions on Summit and the ABA school fields on Keystone so their drafts can be completed.
