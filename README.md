# AuthOps

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

See [reports/REPORT.md](reports/REPORT.md) for every table. Headline numbers from the offline
configuration (rules extractor, deterministic playbook policy):

| Area | Metric | Result |
|---|---|---|
| Extraction, rules baseline (160 docs, 1,680 fields) | field accuracy / precision when answered / silent error | 91.6% / 98.5% / 1.4% |
| Extraction by image condition | accuracy clean / scan / fax | 96.8% / 93.8% / 83.9% |
| Extraction, hardest template (dot-leader, monospace) | accuracy / coverage | 70.0% / 74.1% (it abstains instead of guessing: 94.4% precision) |
| Document type classification | accuracy | 96.3% |
| Validation (80 cases, 24 simulated payor denials) | denials caught before submission / false blocks | 24 of 24 / 0 |
| Browser agents, 3 sandbox portals (34 runs) | verified submit rate / mean smoothness / p50 duration | 34 of 34 / 98.4 / 1.98 s |
| Chaos survived in those runs | session kicks / 5xx retries / stale credential | 32 kicks, 503s retried, stale credential disabled before lockout |
| Ablation: overlay guard off (8 runs) | submitted | 2 of 8 (vs 8 of 8 with the guard) |
| Ablation: no consecutive-failure threshold (9 runs) | portal lockouts | 1 (vs 0 with threshold 2) |
| QA ramp | human-QA share after 12 clean runs | 1.00 -> 0.40 on two portals |
| FHIR PA API (Da Vinci PAS shape) | submitted | 10 of 10 |
| Phone agent (IVR, benefits + status) | calls completed | 24 of 24 |

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
