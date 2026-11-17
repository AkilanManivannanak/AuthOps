# Playbook: Northwind Health Plan (commercial portal)

Owner: AI Ops. Editable by non-engineers. The LLM agent reads this file as-is.

1. Sign in with the leased credential (use `type_credential`; never type passwords yourself).
2. A "Tell us how we're doing" survey may cover the home page. Close it with "No thanks". Never take the survey.
3. Open "New Prior Authorization".
4. Member ID exactly as on the intake record. Date of birth is a date picker.
5. Service Type: pick the specialty (ABA, Physical Therapy, Behavioral Health).
6. CPT and ICD-10 codes comma separated. Units = requested units. Dates are the plan period.
7. Attach the treatment plan PDF under Clinical Documents.
8. Submit, then read the confirmation. The reference number starts with NW-.
9. If the page says the member is not found, do NOT retry with guessed values: finish as needs_human.
