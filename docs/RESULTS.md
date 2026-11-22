# AuthOps: detailed results and methods

Every number here is reproducible from the scripts named in each section. Synthetic patients, fictional payors.

**Live app:** https://akilan-silna-pa-agent.streamlit.app · start at **Join the study** to test it.

> Independent portfolio project by Akilan Manivannan for the Silna Health AI Deployment Analyst application. Not affiliated with or endorsed by Silna Health. All patients, providers and payors are synthetic.

**Prior-authorization agent operations, end to end:** scanned documents in, validated cases out,
submitted through a FHIR API, a browser agent or a phone agent, with experiments, QA review and
metrics around every run.

Built against fictional payors and synthetic patients. No real portal, payor or PHI is touched.
Design rationale and the research it is based on: [docs/DESIGN.md](docs/DESIGN.md).

```
 fax / scan / PDF ──► OCR (word confidence) ──► extraction (rules | Claude, evidence-quoted, abstains)
                                                        │
                                                        ▼
                              validation rules engine (code rules + plain-English LLM rules,
                              payor x specialty requirements)  ──► blocked: fix before submitting
                                                        │ ready
                                                        ▼
                                 channel router:  FHIR PA API  ►  browser agent  ►  phone agent
                                                                   │
                     ┌─────────────────────────────────────────────┼──────────────────────────────┐
                     │ playbook or Claude policy · tool allow-list · overlay guard · credential pool │
                     │ failure classes · loop detection · 50-turn cap · confirmation verification  │
                     └─────────────────────────────────────────────┼──────────────────────────────┘
                                                                   ▼
                     every step in SQLite ─► smoothness score ─► QA review ─► error dataset
                                                    └──► experiments: model arms + QA-share ramp
```

## Results (offline run, 80 cases)

Measured on macOS, Python 3.12.12, Tesseract 5.5.4. A Linux run with Tesseract 5.3.4 lands within
0.5 points on every extraction metric, because the document fonts are bundled in the repo
(`authops/synth/fonts`). Before bundling them, a machine without DejaVu fonts scored 79.5% instead of 91.8%:
rendering, not the extractor, was the variable.

See [reports/REPORT.md](reports/REPORT.md) for every table. Headline numbers from the offline
configuration (rules extractor, deterministic playbook policy):

| Area | Metric | Result |
|---|---|---|
| Extraction, rules baseline (160 docs, 1,680 fields) | field accuracy / precision when answered / silent error | 91.8% / 98.6% / 1.3% |
| Extraction by image condition | accuracy clean / scan / fax | 96.3% / 94.2% / 84.8% |
| Extraction, hardest template (dot-leader, monospace) | accuracy / coverage | 70.6% / 74.7% (it abstains instead of guessing: 94.5% precision) |
| Document type classification | accuracy | 96.3% |
| Validation (80 cases, 24 simulated payor denials) | denials caught before submission / false blocks | 24 of 24 / 0 |
| Browser agents, 3 sandbox portals (34 runs) | verified submit rate / mean smoothness / p50 duration | 34 of 34 / 98.4 / 1.15 s |
| Chaos survived in those runs | session kicks / 5xx retries / stale credential | 32 kicks, 503s retried, stale credential disabled before lockout |
| Ablation: overlay guard off (8 runs) | submitted | 2 of 8 (vs 8 of 8 with the guard) |
| Ablation: no consecutive-failure threshold (9 runs) | portal lockouts | 1 (vs 0 with threshold 2) |
| QA ramp | human-QA share after 12 clean runs | 1.00 -> 0.40 on two portals |
| FHIR PA API (Da Vinci PAS shape) | submitted | 10 of 10 |
| Phone agent (IVR, benefits + status) | calls completed | 24 of 24 |

| Trained confidence calibrator (held-out cases) | AUROC learned vs heuristic | 0.965 vs 0.968: it beat the first heuristic (0.954 vs 0.905), then a date-scoring fix caught up with it; kept for retraining on human labels |

### Claude vs rules (same 80 cases, offline baseline vs Claude Haiku 4.5)

| | Rules baseline | Claude Haiku 4.5 |
|---|---|---|
| Extraction field accuracy | 91.8% | 95.9% |
| Docs with every critical field right | 68.8% | 78.7% |
| Silent error (wrong value filled in) | 1.3% | 2.1% |
| p50 latency per document | 0.8 s | 4.6 s |
| Portal runs verified (50/50 experiment) | 19 of 19 (scripted playbook) | 15 of 15 |
| p50 seconds per portal run | 1.1 s | 16.7 s |
| Cost of the full run | $0 | $1.13 (501 calls) |

Claude reads more of each document but fills in slightly more wrong values, so the deployment
answer is a hybrid: Claude extracts, and fields where it disagrees with the rules go to human QA.

### Three iterations of failure analysis on the Claude agent

| Iteration | Verified | What failed | Root cause | Fix |
|---|---|---|---|---|
| 1 | 13 of 15 | Summit login; Keystone after a correct submit | Playbook told the model to give up on "Invalid credentials" even after the runtime swapped in a good credential; model paraphrased the finish status | Playbook wording; status normalisation gated by the confirmation check |
| 2 | 13 of 15 | Two Keystone runs escalated after a verified submit; one Summit run submitted with a blank NPI | Escalation was non-deterministic (could not reproduce on rerun); NPI field not required by the portal and not on the confirmation page, caught only by QA review | Model's stated reason now logged on every finish; pre-submit guard blocks forward buttons while required clinical fields are empty |
| 3 | 15 of 15 | none | | |

Iteration 1 is kept in `reports/REPORT_llm_iteration1.md`.

### Bugs the harness caught in my own agent

Each of these was found by a failing run in the step table, then fixed and re-run:
1. **Calendar year rollover.** Setting the year before stepping months moved Dec to Jan of the next
   year, so a 2027-03-04 date landed in 2028. Fix: step months first, then set the year.
2. **Function name shadowed by a form field.** `onchange='svc(...)'` resolved to the `<select name='svc'>`
   itself, so ABA conditional fields never appeared. (A portal bug, but exactly the kind real portals have.)
3. **503 then replay.** After going back from a 503, the URL was unchanged, so the playbook thought the
   page was already done. Fix: reset the page on resubmit.
4. **Retry looked like a loop.** Two 503s in a row made loop detection fire on the deliberate replay.
   Fix: clear the loop window on a classified transient retry. Verified submit rate went 33/34 -> 34/34.

**Read these numbers with the limits in mind** (also in DESIGN.md §6):
- I built the sandbox portals and the playbooks, so the playbook arm passing them shows the
  controls work, not that it generalizes. The Claude arm is the generalization test.
- Validation recall is high partly by construction: most simulated denials come from gap types the
  rules know about. One payor policy change is planted that the rules do not know (Keystone PT
  limited to 20 visits); it only shows up when a case lands in that window.
- Rendered documents are cleaner than real faxes (no handwriting, stamps or multi-column layouts).

## Care readiness

Work that happens before and between submissions. Synthetic data; reproduce with
`python scripts/run_care_readiness.py` (add `--llm` for the Claude arms).

| Capability | Implementation | Result |
|---|---|---|
| Long-chart validation | `docagent/`: 12-150 page charts with distractors and answer keys; a background agent that searches, reads and records a cited verdict per rule | Claude Haiku 4.5, 30 charts: 0 false passes vs 5 for a single call; 97.9% vs 85.1% accurate on 100+ pages; $0.057 vs $0.013 and 25s vs 10s per chart |
| Coverage and authorization monitoring | `monitor/`: 26-week panel with coverage lapses, payor switches, partial approvals; unit burn-down forecast | Weekly monitoring cut denied revenue 91% vs reacting to denials (89-92% across 5 seeds) |
| Benefits verification calls | `benefits/`: spoken numbers, self-corrections, remaining-vs-met, plan-pays phrasing, carve-outs, ASR teen/ty swaps; read-back; patient cost estimate | Field accuracy 83.2% -> 94.1% -> 99.4% with read-back; 12-visit estimate error $473 -> $28 |
| Clinical case management | `cases/`: SLA clocks, reminders at 50% and 80%, escalation, audit trail | Covered by tests |
| External API | `api/`: `/v1` with API keys, idempotency keys, HMAC-signed webhooks | Covered by tests |

### Long-chart validation (30 charts, 8 rules each)

| Arm | Accuracy (decided) | Coverage | Accuracy on 100+ pages | False passes | Charts fully right | p50 time | Cost per chart |
|---|---|---|---|---|---|---|---|
| Claude, one call over the whole chart | 0.932 | 0.988 | 0.851 | 5 | 17/30 | 9.7s | $0.013 |
| Claude, background agent (search, read, record) | 0.991 | 0.975 | 0.979 | 0 | 28/30 | 24.99s | $0.057 |
| Offline single pass (first match, context budget) | 0.938 | 0.804 | 0.957 | 3 | 16/30 | 0.0s | $0.000 |
| Offline document finder (template-aware) | 1.000 | 1.000 | 1.000 | 0 | 30/30 | 0.0s | $0.000 |

- A single call degrades with length: 97.9% on charts up to 40 pages, 85.1% on 100+. Three of its five false passes are unsigned or stale plan signatures on 100-150 page charts, where a signed consent form elsewhere looks like the answer.
- The background agent made no false passes at about 4x the cost and 2.5x the latency, so it runs asynchronously, not in the request path.
- Every verdict cites pages and verbatim evidence. The first Claude run exposed a bug in that check (correct cross-page answers rejected because two quotes were joined); the fix checks each piece separately and still rejects any changed number.
- The offline arms only exercise the harness without an API key; the template-aware finder's perfect score says nothing about model quality.

### Coverage monitoring (200 patients, 26 weeks, mean of 5 seeds)

| Policy | Denied visits | Denied dollars | Days without a valid auth | Reauths | Eligibility checks |
|---|---|---|---|---|---|
| reactive | 3649 | $1,031,008 | 10748 | 457 | 0 |
| scheduled | 1737 | $521,400 | 4367 | 541 | 1400 |
| proactive | 332 | $96,652 | 783 | 587 | 5200 |

The panel is deliberately stressed (45% Medicaid, 30% partial approvals, short PT auths); compare policies, not absolute dollars.

## Configuration, prompts and reporting

| Capability | Implementation | Result |
|---|---|---|
| Playbook drafting | `agent/autoconfig.py` walks a portal sandbox once with a test patient: label-to-field mapping, decoy buttons ignored, calendar widgets and masked IDs handled, attestations checked | 8 of 12 walks reach a confirmation, 3/3 on **Lakeshore**, a portal with no hand-written playbook; 92.6% of hand mappings reproduced, 0 wrong, same result with the Claude mapper. Stopped walks list the fields that need a specialist (ABA school schedule, clinical yes/no questions). Drafted playbooks pass the browser end-to-end tests |
| Prompt registry and regression gate | `prompts/<id>/<version>.yaml` with owner, status, hypothesis and fingerprint; `scripts/backtest_prompt.py` | extract@v2 vs production v1 on 60 golden docs: accuracy 0.957 -> 0.952, ICD-10 0.933 -> 0.900, signature 1.000 -> 0.967. **Blocked**; v1 stays in production |
| Weekly operations report | `scripts/write_ops_report.py` from run artifacts | [reports/WEEKLY_OPS_REPORT.md](reports/WEEKLY_OPS_REPORT.md) |

## Keeping rules and playbooks current

| Capability | Implementation | Result (synthetic, reproducible) |
|---|---|---|
| Payor policy drift detection | `intel/drift.py`: one-sided CUSUM per payor x specialty x denial reason (pooled prior), new-reason trigger, partial-approval clustering for soft caps, turnaround shift; each alarm proposes a requirements edit with rates before and after and example decisions. App: **Denial Shield** | 20 streams of 26 weeks with 4 planted changes and a volume-surge decoy: unit caps, new requirements and turnaround shifts detected 100% with median delay 0 weeks and the correct rule proposed; soft caps 90%. 0.9 false alarms per 26 weeks across 10 payor x specialty pairs. 221 denials before the rule is live vs 1,210 if found 6 weeks after the change |
| Self-healing playbooks | `agent/heal.py`, `scripts/canary.py`: daily form fingerprints; on a release, re-draft, keep hand-written judgment steps, verify in the sandbox, emit a patch for review. App: **Playbook Studio** | Northwind redesign (10 relabeled fields, reordered form, new button): detected, re-mapped and verified; the approved playbook fails in the browser and the healed one submits (`test_portal_release_breaks_playbook_and_heal_recovers`). A new required question is returned for a specialist instead of guessed |

## Before and after the payor decision

| Capability | Implementation | Result (synthetic, reproducible with `python scripts/run_intel.py`) |
|---|---|---|
| Approval outlook | `intel/approval.py`: gradient-boosted P(full approval) learned from 40 weeks of decisions (handles the censoring: a full approval only shows the payor's ceiling was not reached); recommends the largest request that clears a target probability. App: **Denial Shield** | 12 held-out weeks, target 80%: full approval on first pass 37.9% -> 86.7% (fixed 15% haircut: 68.0%); partial approvals 62.1% -> 13.3%. Beats the haircut on units approved as well (137,172 vs 134,442), and gives up 4.7% of first-pass units vs asking for the full clinical need, which is why the target is a setting. AUC 0.97 |
| Appeal packets | `appeals/packet.py`: denial reason -> rule -> evidence search in the chart -> appeal, corrective resubmission or specialist review; letters drafted only from verbatim quotes, every citation re-verified (editing a quote breaks verification). App: **Cases and API -> Appeals** | 30 denials on 12-150 page charts (18 wrongful, 12 correct). Claude document agent as the finder: triage 96.7% (29/30), 0 appeals filed on correct denials, 1 wrongful denial routed to resubmission instead of appeal, 17/17 letters with verified citations that cite the deciding page. The template-aware offline finder scores 30/30, which only shows the pipeline works |

## The app

An interactive Streamlit app puts every part of the system in front of a person:

| Page | What you do |
|---|---|
| Command center | Count-up KPIs and flip cards that show how each number was measured |
| Document Lab | Generate a letter or treatment plan (choose payor layout, outcome, clean/scan/fax), watch the AI read it with highlighted evidence, move the abstain threshold, correct the fields, and see AI vs you against ground truth |
| Denial Shield | Build a request and watch the payor rules check it live; see the approval outlook and recommended units; send it to the simulated payor; replay the decision stream to review policy-drift alerts |
| Agent Theater | Run the browser agent live on a sandbox portal with chaos sliders and safety toggles, or scrub through recorded runs step by step; diagnose a failed run |
| QA Console | Grade extracted fields against the document; your verdicts are scored against truth and other reviewers (Cohen's kappa) |
| Autonomy Ramp | Plant a portal regression and watch the QA gate catch it versus a fixed QA share |
| Playbook Studio | Edit a portal's executable plan and backtest it live; simulate a portal release and review the healed playbook |
| Phone Agent | Watch an IVR call, or play the payor rep yourself |
| FHIR and channels | CMS-0057-F timeline, routing decision, PAS bundle, live submit |
| Study and evidence | Every usage number computed from real tester activity, plus a claim builder |

Run locally: `streamlit run streamlit_app.py`.

### Deploy to Streamlit Community Cloud
1. share.streamlit.io, New app, pick this repo, branch `main`, main file `streamlit_app.py`.
2. `packages.txt` installs Tesseract and Chromium; `requirements.txt` installs the rest.
3. Settings, Secrets: add `DATABASE_URL` (free Neon or Supabase Postgres) so tester data survives redeploys,
   `ADMIN_KEY` for the CSV export, and optionally `ANTHROPIC_API_KEY`. See `.streamlit/secrets.toml.example`.
4. Follow [docs/USER_STUDY.md](docs/USER_STUDY.md) to invite testers. Only claim what the Study page computes.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium        # browser for the agents
brew install tesseract                       # or: apt-get install tesseract-ocr
pytest -q                                    # unit + LLM-path (fake model) + end-to-end portal tests
python scripts/run_all.py                    # full offline pipeline -> reports/
```

With Claude (adds a Claude extractor arm, plain-English validation rules and a 50/50
playbook vs Claude agent experiment):

```bash
cp .env.example .env    # put ANTHROPIC_API_KEY=... in .env (never commit it)
python scripts/run_all.py --llm
```

Watch the agent work: `AUTHOPS_HEADED=1 python scripts/run_all.py --cases 12`.

## What is where

| Path | What it does |
|---|---|
| `authops/synth/` | Fictional payors, providers, patients and cases; renders treatment plans and approval/denial letters as clean, scanned and fax images with ground truth |
| `authops/docintel/` | OCR with word confidence, rules and Claude extractors, field-level evaluation |
| `authops/validation/` + `configs/payor_requirements.yaml` | Rules engine: deterministic rules, LLM yes/no rules, payor x specialty requirements |
| `authops/portals/` | Three sandbox payor portals with real-world failure modes, plus a mock FHIR PA endpoint |
| `authops/agent/` | Observation (frames, occlusion), tools, credential pool, runtime, playbook and Claude policies |
| `playbooks/` | Per-portal playbooks: `.md` for people and the LLM, `.yaml` for the deterministic policy |
| `authops/ops/` | Run store (SQLite), smoothness score, experiments and QA ramp, QA reviewer |
| `authops/channels/router.py` | FHIR first, portal second, phone third; Da Vinci PAS shaped bundle |
| `authops/phone/ivr.py` | IVR + hold + rep simulator, phone agent with speech normalization and ASR correction |
| `docs/LEARNING_GUIDE.md` | Domain primer, code walkthrough, exercises, interview talk track |

## Query the runs

```sql
-- sqlite3 reports/authops.db
SELECT portal, COUNT(*) runs, AVG(status='submitted') submit_rate, AVG(smoothness) smooth, AVG(retries) retries
FROM runs WHERE arm='playbook' GROUP BY portal;

SELECT tool, error_class, COUNT(*) n FROM steps WHERE ok=0 GROUP BY 1,2 ORDER BY n DESC;

SELECT r.portal, s.idx, s.tool, s.detail FROM steps s JOIN runs r USING(run_id)
WHERE r.status!='submitted' AND r.arm='playbook' ORDER BY r.run_id, s.idx;
```
