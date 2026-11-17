# Real-user study protocol

The point of the study is simple: every usage claim about AuthOps must be backed by rows a person
actually created, with timestamps. The app computes every number on the **Study and evidence** page
from those rows. Nothing is seeded.

## 1. Before inviting anyone

1. Create a free Postgres database (Neon or Supabase). Copy its connection string.
2. In Streamlit Cloud: app settings, then Secrets. Add:
   ```
   DATABASE_URL = "postgresql://...?...sslmode=require"
   ADMIN_KEY = "a passphrase only you know"
   ```
   Without `DATABASE_URL` the app falls back to SQLite, which Streamlit Cloud wipes on every redeploy.
3. Open the app yourself, join as a tester named `pilot-owner`, do all five tasks. Delete nothing; just
   exclude yourself when you report (the export includes tester names).

## 2. Who to invite

Aim for 8 to 12 people. Engineers are fine; the tasks need no healthcare background. If you can get
two or three people with revenue-cycle, billing or clinic front-desk experience, report them separately:
they are the closest proxy to Silna's authorization specialists.

## 3. Invite message (paste-ready)

```
Hi [name], I built a prior-authorization AI operations tool and I'm running a short usability study.
It takes about 20 minutes, all data is synthetic (no real patients), and you can stop anytime.
You'll review documents the AI read, grade its extractions, run a browser agent against sandbox
insurance portals, and fill a 10-question usability survey.
Link: [app URL]  ->  start at "Join the study".
Your reviews are used only in aggregate (counts, agreement rates, averages). Thanks!
```

## 4. Tasks (shown on the Join page with live checkmarks)

| # | Task | Where | Completion is logged when |
|---|---|---|---|
| T1 | Review and correct 3 AI-read documents | Document Lab | 3 distinct documents submitted |
| T2 | Grade 5 extraction results field by field | QA Console | 5 items submitted |
| T3 | Run a live agent with chaos on, then diagnose the failed replay | Agent Theater | correct diagnosis selected |
| T4 | Find a request the rules pass but the payor denies | Denial Shield | a rules-ready request is denied by the payor |
| T5 | Answer the System Usability Scale | Join page | survey submitted |

## 5. What gets measured

| Measure | Definition | Why it matters for the role |
|---|---|---|
| AI vs human-corrected field accuracy | per field, against ground truth | shows the value of the human-in-the-loop step |
| AI errors fixed by reviewers | AI-wrong fields that the reviewer corrected | the QA step's catch rate |
| Reviewer agreement with truth | share of QA verdicts that match ground truth | reviewer quality |
| Inter-rater reliability | mean pairwise Cohen's kappa on fields rated by both reviewers (5+ shared) | whether the QA rubric is clear enough to scale |
| Time per document / item | seconds from opening to submitting | cost of human review |
| Task completion | testers completing each task | usability of each workflow |
| SUS | System Usability Scale, 0 to 100 (68 is average) | standard usability benchmark |

## 6. Reporting honestly

Use the sentence the **Claim builder** box produces, with its date range. For example:

> User-tested by 9 testers (ML / AI engineer, Software engineer), 31 documents reviewed,
> 412 field-level QA verdicts, inter-rater kappa 0.74, SUS 79/100 (n=9), Nov 18 to Nov 25, 2026.

Do not round up, do not count yourself, and do not describe testers as authorization specialists unless
they are. If kappa is low, report it: it is a finding about the rubric, and that is exactly the
"identify areas for improvement" work the role describes.

## 7. Deleting a tester's data

A tester can ask to be removed. Run against the database:
```sql
DELETE FROM doc_labels WHERE tester_id = '<id>';  -- repeat for qa_labels, task_results, surveys,
DELETE FROM testers WHERE tester_id = '<id>';     -- agent_runs, events, sessions
```
