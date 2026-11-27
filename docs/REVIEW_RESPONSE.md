# Response to the November 2026 reviews

**Reviews:**
- Chrisen: browser agents, X12 278 and FHIR, accounts and data handling, tests.
- Akila: document reader, OCR and checks.
- Walkthroughs of the patient, clinic and operations flows.

All were done at commit `32b7302` on synthetic data. Every finding below was reproduced first, then fixed with a regression test, unless the row says otherwise.

**Totals:**
- Tests: 115 to 152.
- Lint: `ruff check .` passes on the current release. The rules are set explicitly in `pyproject.toml`, the version is pinned in the dev extras and CI, and CI runs exactly `ruff check .` and `pytest`.

## Headline: the reader, before and after

`scripts/eval_reader.py` covers 56 synthetic letters and plans (seed 26). They use the wording the review found hard:
- "sixty (60) days" next to other "within N days" sentences
- partial approvals that never say "partial"
- approval ranges next to a birth date and a letter date
- abbreviated months and 2-digit years
- wrapped reasons
- ZIP codes and phone numbers
- blank signature lines

Each document is rendered to an image and read back by OCR.

| | Fields right | Abstained | Silent errors (a wrong value shown as fact) |
|---|---|---|---|
| Before (`32b7302`) | 59 / 222 | 58 | **105** |
| After | 220 / 222 | 2 | **0** |

The two abstentions are a date OCR misread ("Apri 7"); the reader shows nothing rather than a wrong date. This set was written after reading the review, so it measures the failure modes the review found. It is not a held-out test. `reports/reader_eval.json` has every field.

## Chrisen: agents, standards, accounts, tests

| # | Finding | Fixed by | Test |
|---|---|---|---|
| 1 | `goto` could open any URL; the off-portal check ran a turn too late | The validator judges where a `goto` would go before it runs. `Tools.goto` refuses other hosts. The browser context allows only the portal host for every request (`context.route`) | `test_agent_guards.py` (absolute, protocol-relative and same-host cases) |
| 2 | Token key could be computed from the repo; tokens never expired or ended | No usable default. The key is `AUTHOPS_SECRET`, or a random key made once and kept in the database. Tokens are `account.version.expiry.signature`: they expire after 30 days, and "Sign out on all devices" or deleting the account bumps the version. `AUTHOPS_SECRET` added to the secrets example | `test_sessions.py`: the old constant-key forgery is refused, as are expired, signed-out and tampered tokens |
| 3 | SV1 used `VS` as the unit | SV103 is now `UN`; visits go in `HSD*VS` at the service level. The validator rejects any SV103 other than `UN`/`MJ` | `test_sv1_uses_units_and_visits_go_in_hsd` |
| 4 | Hard-coded delimiters; last HCR wins; no escaping; provider name in one element | Delimiters are read from the ISA. One decision per service line, and mixed lines read as partial. Delimiter characters are removed from data. Provider names are split into last/first without the credential | A hand-written golden 278 response with `\|` and `>` delimiters and mixed lines (`tests/fixtures`), plus an escaping test |
| 5 | FHIR bundle wasn't valid R4 | Added Coverage, payor Organization and Practitioner, `insurance`, `insurer`, references by `fullUrl`, `Bundle.identifier` and `timestamp`; stable ids per request | `Bundle.model_validate` with `fhir.resources` (R4B) |
| 6 | `submit_fhir` crashed on non-JSON; unknown payor raised `KeyError` | Gateway errors and timeouts retry with backoff, then return `needs_human` with an error class. An unknown payor goes to the browser agent | Mock-transport tests: a 502 HTML page, then success; and 502 every time |
| 7 | A real value in the wrong field passed | Per-field check for NPI, member ID, DOB, CPT, ICD-10 and units. Still 0 false blocks on 20 clean Northwind runs | `test_real_value_in_the_wrong_field_is_blocked`, `test_right_values_pass_in_any_date_format` |
| 8 | "Lower to the payor's limit" used the model's number | The issue carries the payor's own limit. The main action is **Split it**: the limit now, the rest kept as a second request. The model's recommendation stays a separate, labelled choice | `test_payor_limit_fix_uses_the_payors_limit_and_keeps_the_rest` |
| 9 | No account deletion; no rate limit | "Delete my account" removes the account, workspace, usage, ratings, AI quota and sessions. Sign-in locks for a minute after 5 failures per email | `test_accounts.py` |
| 10 | Coverage gaps | Accounts, sessions, X12 golden file, FHIR schema and errors, validator, and credential pool (concurrent leases; release after a crash) | 37 new tests |
| 11 | Unpinned ruff | Explicit rule set, pinned version, CI runs `ruff check .` | CI |
| 12 | Auth number changed every run | Fixed clock and a hash of the case id | Visible on Channels |

Not changed: "An account with this email already exists" still says so. It's a common sign-up trade-off, and the sign-in rate limit is the guard. A PAS-profile validation (the official HL7 validator with the Da Vinci package) is still to do; the bundle now passes base R4.

## Akila: document reader

| # | Finding | Fixed by | Test |
|---|---|---|---|
| 1 | "Provider Signature: Date:" counted as signed | The signature has to be a name, not the next label | A real-OCR round trip of the unsigned sample plan, now "fix" |
| 2 | Switching modes showed the previous document's result | Documents are keyed by a hash of their pages, and a new mode starts empty | Recorded journey 8 |
| 3 | "Approved 12 of 24" read as denied | "N of M", or approved and denied wording together, reads as partial, with both numbers | `test_3_*` |
| 4 | First "within N days" won; "sixty (60)" missed | Read only next to "appeal"/reconsideration/fair hearing/peer-to-peer; spelled-out numbers read; a dated letter gives a calendar deadline | `test_4_*`; 40/40 on the eval set |
| 5 | Start date taken from the DOB or letter date | A written range first; loose dates only from lines that aren't DOB, letter or notice dates | `test_5_*` |
| 6 | AI "pass" with no quote, or a quote that only claims the check | An AI pass needs a quote found on the page that isn't a bare claim ("medical necessity is established"); otherwise "unclear". Keyword checks stay unless the AI shows evidence | `test_6_*` |
| 7 | AI decision, amount and dates not checked | Amounts and dates must appear on the page, or they're replaced by the rules value and listed as "not found on the letter". A decision with no supporting wording is flagged | `test_7_*` |
| 8 | "Dec 1, 2026", "Sept 30", "12/01/26" dropped | `parse_date` reads abbreviated months and 2-digit years. The extractor's own results don't change (checked against the old code) | `test_8_*` |
| 9 | Reason cut at the line break | Read to the end of the sentence, whitespace collapsed | `test_9_*` |
| 10 | ZIP codes as CPT, phone numbers as NPIs | No CPT right after a state code; NPIs must start with 1 or 2 and can't follow phone/fax/tel. One bad NPI is now "fix" | `test_10_*` |
| 11 | Uploaded pages stayed on disk | Pages are kept in memory; files exist only while OCR and the model read them, then the folder is deleted. Saved results keep no letter wording | `test_11_*` |
| 13 | Ratings not tied to a document | Each rating stores a document hash, a sample/real flag and a snapshot of what was shown (no free text). Failed saves are shown, not swallowed. Reports split samples from real uploads, and the AI Ops desk opens any "Not quite" rating with its snapshot. Existing databases get the new columns automatically | `test_accounts.py::test_feedback_columns_are_added_to_an_old_table`, `test_analytics.py` |
| 14 | AI cap reset on reload | Counted on the server per account per day, and per network address (hashed) for guests | |

## Walkthroughs

| Observation | Change |
|---|---|
| The patient's sample letter was written to the clinic | Patients get a member notice: addressed to them, dated, a partial approval, "sixty (60) days" |
| The deadline had no calendar date | "by Jan 17, 2027" when the letter is dated; otherwise "60 days from the date printed on the letter" |
| A dead-end "turn on the AI reader" hint | Rule answers show the line they came from ("✓ on the page · appeal deadline") |
| "Units" and "per-request limit" unexplained | An "In plain words" line under the payor's reason |
| The funnel never counted people who left at sign-in | A landing row is logged for every visit |
| "AI answers" included rule answers | Renamed "Answers people rated (AI and rule checks)", split by layer and by sample/real |
| Reviewers scored on fields they couldn't see | 33 answer-key fields printed on page 2 of plans are shown as "on a later page, not scored" |
| "Reviewer disagreed" was unclear | Renamed "differs from answer key" |

Still open: toasts can cover the account chip; the usage page has no date filter.

## Walkthroughs, round 2 (Nov 26, on `4fbf999`)

| Observation | Fix | Test |
|---|---|---|
| The plan's diagnosis showed as "M54." when the page says M54.50 (OCR wrote "M54. 50") | Codes split by OCR after the dot are put back together before reading | `test_icd_code_split_by_ocr_is_rejoined` |
| "14 units approved" when the letter says visits | The amount uses the word on the letter (visits, hours, sessions or units), and the requested amount is shown next to it | `test_amount_uses_the_letters_own_word` |
| A patient stayed in "Ready to send / Passed every check" while the readiness check said it was over the payor's limit | A ready request is re-checked every time the board, counts or suggestions are drawn. Sending refuses a request with an open issue, on the server, not only in the UI | `test_board_rechecks_ready_requests_and_send_refuses_open_issues` |
| After splitting to the payor's limit (400), the outlook said 0% and recommended 268 with no explanation | Explains that the limit is the most you may ask for, not what is usually approved in full; shows "under 1%" instead of 0%; says both choices are allowed | Visible on Prior authorizations |
| "Hours", "visits" and "units" mixed on one screen | Rule messages use the patient's own unit; "Above the payor's unit limit" now reads "More than the payor allows in one request" | |
| "Use by role" summed to 42 against 29 sessions ("not chosen yet: 13") | Each session counts once, under the last role it picked; "left before choosing" means exactly that, and the table sums to the funnel | `test_reports_count_what_happened` |
| The tester steps asked for a third rating that wasn't possible (one fixed sample, already rated) | "Try another sample" rotates through three samples per mode: letters approved, partial and denied; plans unsigned, signed and expired. Each is its own document and can be rated | Recorded journey 9: three letters, three ratings, three document ids |
