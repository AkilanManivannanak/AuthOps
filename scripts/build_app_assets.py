"""Build the small, versioned assets the Streamlit app ships with.

  app/assets/qa/        40 review items: a document image plus what the extractor produced
  app/assets/replays/   4 recorded browser-agent runs, one screenshot per step
  app/assets/*.json     metrics, risk-coverage curves, calibrator weights

Run after scripts/run_all.py:  python scripts/build_app_assets.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from authops.docintel.extract import RuleExtractor  # noqa: E402
from authops.docintel.evaluate import values_match  # noqa: E402
from authops.docintel.ocr import ocr_pages  # noqa: E402
from authops.schemas import DocType  # noqa: E402

DATA, REPORTS, ASSETS = ROOT / "data", ROOT / "reports", ROOT / "app" / "assets"


def build_qa_items(n_letters: int = 20, n_plans: int = 20) -> None:
    out = ASSETS / "qa"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    manifest = json.loads((DATA / "manifest.json").read_text())
    letters = [d for d in manifest if d["doc_type"] in ("approval_letter", "denial_letter")][:n_letters]
    plans = [d for d in manifest if d["doc_type"] == "treatment_plan"][::2][:n_plans]
    ex = RuleExtractor()
    items = []
    for d in letters + plans:
        ocr = ocr_pages(d["pages"][:1])
        e = ex.extract(d["doc_id"], ocr, DocType(d["doc_type"]))
        img = Image.open(d["pages"][0]).convert("L")
        img.thumbnail((1100, 1500))
        img_name = f"{d['doc_id']}.jpg"
        img.save(out / img_name, quality=72)
        fields = []
        for k, t in d["truth"].items():
            if k == "denial_reason" or k not in e.fields:
                continue
            fv = e.fields[k]
            shown = None if fv.abstained else fv.value
            if shown is None:
                auto = "absent" if t is None else "missing"
            else:
                auto = "correct" if values_match(k, shown, t) else "wrong"
            fields.append({"field": k, "value": shown, "conf": fv.confidence, "auto_verdict": auto})
        items.append({"item_id": d["doc_id"], "doc_type": d["doc_type"], "condition": d["condition"],
                      "template": d["template"], "image": img_name, "fields": fields})
    (out / "items.json").write_text(json.dumps(items, indent=1, default=str))
    print(f"qa items: {len(items)}")


def build_replays() -> None:
    from playwright.sync_api import sync_playwright

    from authops.agent.credentials import CredentialPool
    from authops.agent.policy import PlaybookPolicy
    from authops.agent.runtime import AgentRuntime
    from authops.ops.store import Store
    from authops.portals.app import CREDENTIALS, Chaos
    from authops.portals.server import PortalServer

    out = ASSETS / "replays"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    cases = json.loads((DATA / "cases.json").read_text())
    clean = [c for c in cases if not c["injected_gaps"]]
    aba = next(c for c in clean if c["specialty"] == "aba")
    plans = [
        ("northwind_popup", "northwind", clean[0], Chaos(survey_modal_rate=1.0), True),
        ("keystone_aba_iframe_calendar", "keystone", aba, Chaos(), True),
        ("summit_mfa_503_retry", "summit", clean[1], Chaos(summit_503_rate=1.0, summit_kick_rate=0.0), True),
        ("keystone_guard_off_failure", "keystone", clean[2], Chaos(), False),
    ]
    exe = os.environ.get("AUTHOPS_CHROME") or ("/usr/bin/google-chrome" if Path("/usr/bin/google-chrome").exists() else None)
    for name, portal, case, chaos, guard in plans:
        d = out / name
        d.mkdir()
        steps = []

        def on_step(s, shot, d=d, steps=steps):
            fn = f"step_{s['idx']:02d}.jpg"
            if shot:
                (d / fn).write_bytes(shot)
            steps.append(dict(s, image=fn if shot else None))

        with PortalServer(DATA / "cases.json", chaos) as srv, sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=["--no-sandbox"], **({"executable_path": exe} if exe else {}))
            rt = AgentRuntime(b, srv.url, CredentialPool(CREDENTIALS, threshold=5),
                              Store(ROOT / "reports" / "replays.db"), overlay_guard=guard, wall_clock_s=25)
            state = {"n": 0}

            def cb(s, shot, inner=on_step, chaos=chaos, state=state):
                inner(s, shot)
                if s["tool"] == "backoff_resubmit":  # let the payor recover after two 503s
                    state["n"] += 1
                    if state["n"] >= 2:
                        chaos.summit_503_rate = 0.0
            r = rt.run(case, portal, PlaybookPolicy(portal),
                       [str(DATA / "docs" / f"{case['case_id']}_treatment_plan.pdf")], arm=name, on_step=cb)
            b.close()
        (d / "run.json").write_text(json.dumps({
            "name": name, "portal": portal, "case_id": case["case_id"], "guard": guard,
            "status": r.status, "error_class": r.error_class, "smoothness": r.smoothness, "steps": steps,
            "duration_s": r.duration_s, "ref": r.ref, "verified": r.verified, "note": r.note}, indent=1, default=str))
        print(f"replay {name}: {r.status} {r.error_class} {len(steps)} steps")


def copy_reports() -> None:
    for f in ["metrics.json", "risk_coverage.json", "calibrator.json", "agent_runs.json", "REPORT.md", "extraction_rows.json"]:
        if (REPORTS / f).exists():
            shutil.copy(REPORTS / f, ASSETS / f)


if __name__ == "__main__":
    ASSETS.mkdir(parents=True, exist_ok=True)
    copy_reports()
    build_qa_items()
    build_replays()
