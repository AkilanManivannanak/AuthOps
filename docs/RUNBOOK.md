# AuthOps operations runbook

How the system is run day to day: adding a payor or portal, triaging AI errors, deciding how much human review a portal needs, and handling incidents. Every threshold below is the one in the code, with the file it lives in.

## 1. Onboard a new payor

1. **Collect the rules.** From the payor's provider manual and bulletins, note per specialty: the maximum units per request, required attachments, and any rule a person would check by reading (for example "the plan states measurable goals").
2. **Add the payor to `configs/payor_requirements.yaml`.**
   - `name`, and `channel`: `fhir` if the payor offers a prior-auth API, `portal` if requests go through a website, `phone` if neither.
   - Under `specialties`, set `max_units_per_request` and add the reading rules as `custom_rules`, written as yes/no questions.
   - The default code rules (signature, plan dates, billable ICD-10, CPT matches specialty, NPI checksum, member ID prefix, date order) apply automatically.
3. **Check the route.** In the app open *Prior authorizations → Channels* and pick the payor. The route chip should show the channel you set. For a payor that takes X12, the 278 panel must show *Envelope valid*.
4. **Run the rule checks:** `python scripts/run_all.py`. Validation results for the new payor appear in `reports/metrics.json`.
5. **Start in shadow.** A new payor starts with QA share 1.0: every submission is reviewed by a person (see section 4).

## 2. Onboard a new portal

1. **Draft the playbook:** `python scripts/run_autoconfig.py` (add `--llm` to also map labels with the model; only field labels are sent, never patient data or credentials). It writes `playbooks/<portal>.yaml` and scores the draft.
2. **Read the draft** in *AI Ops desk → Playbooks*. Each page has a `match` (URL) and `actions` (fill, click, answer, check_each). Fix any field the draft mapped to the wrong value.
3. **Record approved fingerprints:** `python scripts/canary.py --approve`. These are the page layouts the daily canary compares against.
4. **Debug failures one case at a time:** `python scripts/rerun_cases.py <portal> <policy> PA-0023`, which prints every step.
5. **Credentials** are stored per portal through `authops/agent/credentials.py`. They are never put in a playbook, a prompt or a log.

## 3. Triage AI errors

Sources, most urgent first:

| Source | Where | What it means |
|---|---|---|
| Silent errors | QA review, `reports/metrics.json` | The agent reported success but submitted a wrong value. Treated as an incident (section 5). |
| "Not quite" ratings | *AI Ops desk → Usage and quality*, `what_went_wrong.sql` | A person said the letter reading or plan check was wrong, and which part. |
| Review-queue disagreements | `field_errors.sql` | Fields where the extractor's answer did not match the reviewer's. |
| Validation failures | *Prior authorizations*, rule results | A request was stopped before sending. Usually a missing document rather than an AI error. |

Weekly loop:

1. Run `python -m authops.analytics.reports` and start with `what_went_wrong` and `field_errors`. Fix the top row first.
2. Find whether the AI or the rule checks produced the answer (the `layer` column in `ai_accuracy.sql`). Rule-layer errors are fixed in code with a test. AI-layer errors are fixed in the prompt.
3. Add the failing document to the golden set, then write the prompt change as a new version in `prompts/extract/`.
4. **Backtest before shipping:** `python scripts/backtest_prompt.py --candidate extract@vN`. The gate (`authops/ops/prompts.py: gate`) refuses the change if:
   - overall accuracy falls at all,
   - silent errors rise at all,
   - or any critical field falls by more than 2 points.
5. The candidate is never promoted automatically. Change its status in the YAML once the gate passes, and record why in the commit.
6. Publish the week's numbers: `python scripts/write_ops_report.py` writes `reports/WEEKLY_OPS_REPORT.md`.

## 4. Human review ramp

`authops/ops/experiments.py: QARamp` decides what share of a portal's submissions a person checks. Each portal starts at 1.0 and is re-evaluated after every window of runs (8 by default; the pipeline run in `scripts/run_all.py` uses 6).

- **Step down by 0.3** (to a floor of 0.1) only when every one of these holds:
  - success in the window is at least 90%,
  - smoothness is at least 80,
  - zero silent errors in the window,
  - the 95% Wilson lower bound on all-time clean runs is at least 0.75, so a lucky first window can't remove the human check by itself.
- **Step up by 0.6** (to a maximum of 1.0) when success falls below 75% or any silent error appears.
- **A portal redesign** shows up as failed runs, so the step-up rule sends review back up by itself. The canary usually catches it first; the operator then sets the portal back to 1.0 by hand (section 5), and the repaired playbook earns its way down again. *AI Ops desk → Autonomy* replays this case.

The floor never reaches 0: one submission in ten is always checked.

## 5. Incidents

| Incident | Detect | First action | Close when |
|---|---|---|---|
| Portal redesign | `scripts/canary.py` fingerprint mismatch | Pause that portal's queue; set its QA share to 1.0 | The playbook repair in *Playbooks* passes and new fingerprints are approved |
| Silent error | QA review | Correct the submission with the payor the same day; set the portal's QA share to 1.0 | Root cause has a test and the golden set includes the case |
| Model provider down or erroring | AI calls fail | Nothing: the reader falls back to the rule layer by itself, and results are labelled as rules-only | Calls succeed again |
| Payor rule change | Drift monitor (*Insurance monitoring*) proposes an edit | Review the evidence; approve the edit to `payor_requirements.yaml` | Approved edit merged and checks re-run |
| Reauth about to lapse | *Today* board, reauth window | Start the reauth from the patient's row | The new request is sent |

## 6. Metric definitions

| Metric | Definition | Computed in |
|---|---|---|
| Verified submit rate | Agent runs whose submission was confirmed on the portal, divided by runs, per portal and per model | `reports/metrics.json` → `agents` |
| p50 duration | Median seconds per agent run | `reports/metrics.json` → `agents` |
| Silent error rate | Fields the extractor answered but got wrong, divided by fields scored: the number that sends bad data to a payor | `authops/docintel/evaluate.py` |
| Field accuracy | Extracted fields equal to the truth, divided by fields scored, per field | `authops/docintel/evaluate.py` |
| QA share | Fraction of a portal's submissions routed to a person | `QARamp`, `reports/metrics.json` → `qa_ramp` |
| Funnel | Sessions that opened the app, picked a role, used a tool, rated an AI answer | `authops/analytics/queries/funnel.sql` |
| AI answers rated right | Ratings of "Yes" divided by all ratings, by tool and layer | `ai_accuracy.sql` |

## 7. Data handling

- Only field labels go to the model when playbooks are drafted. Patient documents go to the model only when the person checks a document with AI turned on.
- The API key lives in `.env` locally or Streamlit Secrets in production. It is never shown in the app.
- Usage rows record an account id or a session id, the role, the page and the action. They do not record document contents.
- Uploaded pages are kept in memory and written to disk only while OCR and the model read them; the folder is then deleted. Saved results keep the decision, dates and checks, never the image or the letter's wording.
- Saved sign-ins are signed with `AUTHOPS_SECRET` (or a random key kept in the database), expire after 30 days, and end on every device when the person signs out everywhere or deletes the account. Sign-in locks for a minute after 5 failures.
- "Delete my account" removes the account, its saved work, its usage and ratings, its AI quota and its sessions.
- The browser agent can load only the portal's own host; any other address is refused before it is opened.
- Set `DATABASE_URL` (Postgres) in production so usage and ratings survive redeploys. Without it the store is a local SQLite file.
