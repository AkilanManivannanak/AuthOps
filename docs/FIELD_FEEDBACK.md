# Field feedback: an outpatient physical therapy clinic in Brooklyn

**When:** November 2026
**What:** paperwork from one real patient file (folder, visit log, referral, medication pages), shared with the clinic's agreement and de-identified before anything was run.
**Clinic:** a small outpatient PT practice in Sunset Park, Brooklyn, billing Anthem, Medicaid and Medicare.

## How the pages were de-identified

- Removed every HIPAA Safe Harbor identifier: names (including the Chinese-script name and signature), birth date, every full date (visit, referral, print and medication start dates), address, phone, patient ID, three insurance member IDs, chart number, and the names of the patient's other doctors.
- Cut off the top of one page, which held sensitive history notes.
- Checked the result by running OCR at three zoom levels and searching for every name, number and date pattern. Nothing was found.
- The pages were read on one machine with the AI reader turned off.
- The images are not in this repository. The original photos are deleted once the de-identified copies are made.

## What the paperwork showed

| What was on the page | What it means for the work | What AuthOps did before | What it does now |
|---|---|---|---|
| A phone photo of a printed referral, unevenly lit | Clinics photograph paper; they don't scan it | OCR read "Low back pain (M54.50)" as "Lew nack gain (MS4.50}" and lost the reason for the referral | Reads each page two ways (fax cleanup and phone-photo cleanup) and keeps the one OCR is more sure of; repairs letters inside ICD-10 codes (MS4.50 becomes M54.50) |
| The referral reason was one line; the page also listed 21 past diagnoses | The request must carry the referral's diagnosis, not the history | Reported the first five history codes as "diagnosis codes found" | Finds the referral reason and its code, and says the other codes are history and not for this request |
| A referral, not a plan of care | A referral starts a PT authorization but can't be sent on its own | Graded it like a plan: "no signature, no dates" | Recognises a referral and lists what the payor still needs: an initial evaluation (97161-97163), a plan of care signed by the therapist, visit codes, and the therapist's NPI. Scored 33, not ready |
| First insurance "BCBS Dual Advantage", second Medicaid, third Medicare | A dual-eligible patient on a Medicare Advantage plan: which plan gets the request? | Ignored insurance | Names the primary plan; explains that Original Medicare doesn't pay while the patient is on an Advantage plan and that Medicaid is billed after the primary; maps BCBS and Empire in New York to Anthem Blue Cross and Blue Shield (renamed January 1, 2024, same member IDs) |
| A sticky note "Anthem" on the folder, and "VNS-MC → Anthem" | The patient changed plans; the clinic tracks payor changes by hand | Not modelled | Not yet automated; next item below |
| The authorization number on a sticky note on the visit log | Approved visits are counted on paper | Not modelled for a visit log | Recognises a visit log and asks for the authorization number, approved visit count and end date to be kept with it |
| Visit log columns CP, HP, US, ES, AE, TE, TM, MR, TX, PB, with a bilingual legend | The log uses the clinic's shorthand, not billing codes | Not read | Maps each column to its CPT code (for example US 97035, TE 97110, MR 97140, TX 97012, PB 97018), with notes such as "97010 is usually bundled" |

## Conversation with the clinic

*To be filled in from the conversation notes: who (role only), what they said in their own words, and what they asked for.*

## What changed in the code

- `authops/assist/reader.py`:
  - phone-photo OCR path
  - `_icd_fix`
  - `referral`
  - `insurances`
  - `send_auth_to`
  - `modality_codes`
  - `check_referral`
  - a visit-log result
- `tests/test_field_clinic.py`: six tests on invented text with the same shape as the real pages.
- `tests_ui/j_clinic_paperwork.py`: a recorded browser run on the de-identified pages, 11/11 checks. It needs the images locally; they are not committed.

## Next, from this file

1. **Plan change:** when a patient's plan changes (as with VNS to Anthem here), start a new authorization with the new plan, and stop counting visits against the old one.
2. **Visit counter:** approved visits, visits used from the log, and the end date, with an alert before either runs out.
3. **Initial evaluation reader:** read the 3-page IE the clinic sends with the referral, and fill the plan-of-care checks from it.
