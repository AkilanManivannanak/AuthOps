import streamlit as st

from app.ui import ROOT, asset_json, setup

setup("Method and limits", "How every number in this app was produced, and what it does not prove.")

m = asset_json("metrics.json") or {}
env = m.get("env", {})
st.markdown(f"""
**Data.** {m.get('cases', 80)} synthetic prior-auth cases across five fictional payors and three specialties
(ABA, physical therapy, behavioral health). Treatment plans and payor letters are rendered as clean, scanned and
faxed images with known ground truth. Fonts are bundled so rendering is identical on every machine.
Environment of the published run: Tesseract {env.get('tesseract', 'n/a')}, Python {env.get('python', 'n/a')}, {env.get('os', 'n/a')}.

**Extraction.** OCR with word confidence, then a rules extractor with validators (NPI checksum, ICD-10 shape, date
order). Fields below a confidence threshold abstain. A logistic calibrator is trained on held-out cases to predict
whether a value is correct. Metrics: field accuracy, precision when answered, coverage, silent error.

**Validation.** Deterministic payor rules plus optional plain-English rules answered strictly yes/no by an LLM.

**Agents.** Playwright browser agent on four sandbox portals (one held out, no hand-written playbook) built with
common portal failure modes. Guards, failure classification, credential pool, loop detection, 50-turn cap, confirmation check.
Every step is persisted. Smoothness score 0-100 is separate from the outcome.

**Keeping rules and playbooks current.** Payor decisions are monitored with one-sided CUSUM per denial reason,
a new-reason trigger, partial-approval clustering (soft caps) and a turnaround monitor; each alarm proposes a rule
with evidence for approval. A daily canary fingerprints every portal form; on a release the changed steps are
re-drafted, judgment steps are kept, and the candidate must reach a confirmation in the sandbox before review.

**Real-user study.** Testers consent, then their corrections, QA verdicts, task times and SUS answers are stored
with timestamps. Agreement is Cohen's kappa over reviewer pairs on shared fields. Nothing is seeded.

**What this does not prove**
- The sandbox portals and the playbooks were written by the same person. Passing them shows the controls work.
  Lakeshore is held out and drafted automatically, and the Claude mapper matches without a lexicon, but only a
  real portal proves generalization.
- Most simulated denials come from gap types the rules know by construction. One hidden payor rule is planted.
- Rendered documents are cleaner than real faxes: no handwriting, stamps or multi-column scans.
- Tester numbers measure this app with these synthetic documents, not production performance.
""")
rep = ROOT / "app" / "assets" / "REPORT.md"
if rep.exists():
    with st.expander("Full evaluation report"):
        st.markdown(rep.read_text())
