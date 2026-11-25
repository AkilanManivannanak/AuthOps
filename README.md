# AuthOps

**Prior-authorization operations, end to end: read the documents, catch denials before they happen, submit through any channel, and keep rules and playbooks current on their own.**

[![Live app](https://img.shields.io/badge/live%20app-open-28543E?style=for-the-badge)](https://akilan-silna-pa-agent.streamlit.app)
![tests](https://img.shields.io/badge/tests-89%20passing-28543E?style=for-the-badge)
![data](https://img.shields.io/badge/data-synthetic%20only-9A9A9A?style=for-the-badge)

![AuthOps demo](docs/media/demo.gif)

**Accounts and roles:** sign in, choose patient, clinic or AI operations, and work on one shared workspace where every action shows up on every page, with "Next up" suggestions.

**Use it on a real document:** on *Try it on your document*, a patient or family can upload an insurance letter and get the
decision, dates, appeal deadline and next steps in plain English; a clinic can upload a treatment plan and see what to fix
before it goes to the payor. Claude reads the page; deterministic checks (NPI checksum, ICD-10 and CPT shape, dates,
signature) run alongside it, and every quote the AI returns is checked against the page. Nothing is stored.

> Independent portfolio project by Akilan Manivannan. Not affiliated with or endorsed by Silna Health. The demos use synthetic patients, providers and payors.

## How a request moves

```mermaid
flowchart LR
    A[Fax / scan / PDF] -->|OCR + extraction| B(Structured request)
    B --> C{Payor rules}
    C -->|gap found| X[Fix before sending]
    C -->|ready| D[Approval outlook<br/>recommended units]
    D --> E{Channel}
    E -->|FHIR API| F[Payor]
    E -->|Browser agent| F
    E -->|Phone agent| F
    F -->|approved| G[Coverage monitor<br/>reauth timing]
    F -->|denied| H[Appeal packet<br/>or corrective fix]
    F -.->|decision stream| I[Policy drift monitor]
    I -.->|proposed rule| C
    J[Portal canary] -.->|self-healed playbook| E
```

## What it does

| | |
|---|---|
| 📄 **Reads documents** | OCR + field extraction with confidence; abstains when unsure. Long charts (12-150 pages) checked by a background agent that cites every page |
| 🛡️ **Prevents denials** | Payor rules block gaps before submission; an approval model recommends how many units to request |
| 🤖 **Submits anywhere** | Browser agent on four sandbox portals (pop-ups, iframes, MFA, lockouts), FHIR prior-auth API, phone IVR |
| 📡 **Stays current** | Detects unannounced payor rule changes from the decision stream; heals playbooks when a portal is redesigned |
| ⚖️ **Handles denials** | Triage: appeal with verified citations, corrective resubmission, or specialist review |
| 📈 **Earns autonomy** | Human QA share drops only while results hold; prompt changes pass a regression gate |

<p>
<img src="docs/media/agent.png" width="49%" alt="Browser agent on a sandbox portal"/>
<img src="docs/media/drift.png" width="49%" alt="Policy drift alert"/>
<img src="docs/media/outlook.png" width="49%" alt="Approval outlook"/>
<img src="docs/media/heal.png" width="49%" alt="Self-healing playbook"/>
</p>

## Results

| | |
|---|---|
| **0 vs 5** | false passes, background document agent vs a single model call, on 30 charts up to 150 pages |
| **86.7%** | requests approved in full on first pass with the unit recommendation (37.9% asking for the clinical need) |
| **100%** | unit caps and new payor requirements detected, median 0 weeks after the change |
| **3 / 3** | submissions on a portal nobody configured by hand (auto-drafted playbook) |
| **96.0%** | fields read correctly from 160 faxes and scans, 0.5% wrong without a human check (91.8% and 1.3% before checksum and format-guided OCR repair) |
| **4 → 0** | wrong-data submissions with the turn validator when 25% of typed values are corrupted (0 false blocks in 40 clean runs) |
| **99.4%** | benefits-call fields correct with read-back (83.2% without) |
| **17 / 17** | appeal letters with every citation verified against the chart |

All numbers come from synthetic data and are reproducible. Methods, every table and the limits: **[docs/RESULTS.md](docs/RESULTS.md)** · design: **[docs/DESIGN.md](docs/DESIGN.md)**.

## Run it

```bash
pip install -r requirements.txt && python -m playwright install chromium
python scripts/run_all.py          # full pipeline, writes reports/
streamlit run streamlit_app.py     # the app
```

`pytest -q` runs 63 tests, including real-browser runs on every sandbox portal.
