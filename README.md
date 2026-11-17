# AuthOps

**Live app:** _add your Streamlit URL here after deploying_ · start at **Join the study** to test it.

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

| Trained confidence calibrator (held-out cases) | AUROC learned vs heuristic | 0.963 vs 0.977: it beat the first heuristic (0.954 vs 0.905), then a scoring fix overtook it; kept for retraining on human labels |

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

## The app

An interactive Streamlit app puts every part of the system in front of a person:

| Page | What you do |
|---|---|
| Command center | Count-up KPIs and flip cards that show how each number was measured |
| Document Lab | Generate a letter or treatment plan (choose payor layout, outcome, clean/scan/fax), watch the AI read it with highlighted evidence, move the abstain threshold, correct the fields, and see AI vs you against ground truth |
| Denial Shield | Build a request, watch the payor rules check it live, send it to the simulated payor, and hunt for the hidden policy change |
| Agent Theater | Run the browser agent live on a sandbox portal with chaos sliders and safety toggles, or scrub through recorded runs step by step; diagnose a failed run |
| QA Console | Grade extracted fields against the document; your verdicts are scored against truth and other reviewers (Cohen's kappa) |
| Autonomy Ramp | Plant a portal regression and watch the QA gate catch it versus a fixed QA share |
| Playbook Studio | Edit a portal's executable plan and backtest it live |
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
