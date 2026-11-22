"""Draft playbooks automatically for every sandbox portal and score them.

    python scripts/run_autoconfig.py          # lexicon mapper (offline)
    python scripts/run_autoconfig.py --llm    # adds the Claude label mapper (labels only, no PHI or credentials)

For each portal x specialty: did one sandbox walk reach a confirmation, which fields were left
for a person, and how many of the hand-written playbook's field mappings the draft reproduced.
Lakeshore has no hand-written playbook: it is the held-out portal.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pyotp  # noqa: E402
import yaml  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from authops.agent.autoconfig import compare, draft_playbook  # noqa: E402
from authops.portals.app import CREDENTIALS, Chaos, create_app  # noqa: E402
from authops.synth.generate import generate_cases  # noqa: E402

STARTS = {"northwind": "/northwind/login", "keystone": "/keystone/login", "summit": "/summit/login",
          "lakeshore": "/lakeshore/signin"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    args = ap.parse_args()
    cases = [c.model_dump(mode="json") for c in generate_cases(40, seed=5, gap_rate=0.0)]
    cf = Path(tempfile.mkdtemp()) / "cases.json"
    cf.write_text(json.dumps(cases))
    mappers = ["lexicon"] + (["claude"] if args.llm else [])
    llm = None
    if args.llm:
        from authops.llm import ClaudeLLM
        llm = ClaudeLLM()
    rows, drafts = [], {}
    for mapper in mappers:
        for portal, start in STARTS.items():
            for spc in ("aba", "physical_therapy", "behavioral_health"):
                case = next(c for c in cases if c["specialty"] == spc)
                cred = CREDENTIALS[portal][0]
                totp = (lambda c=cred: pyotp.TOTP(c["totp"]).now()) if "totp" in cred else None
                cl = TestClient(create_app(cf, Chaos(survey_modal_rate=0, summit_503_rate=0, summit_kick_rate=0)))
                t0 = time.perf_counter()
                d = draft_playbook(cl, portal, start, cred, case, mapper=mapper, llm=llm, totp=totp)
                hand = ROOT / "playbooks" / f"{portal}.yaml"
                cmp = compare(yaml.safe_load(hand.read_text()), d.spec) if hand.exists() else None
                flagged = sorted({u for pg in d.pages for u in pg["unmapped"]})
                rows.append({"mapper": mapper, "portal": portal, "specialty": spc, "reached": d.reached_confirmation,
                             "stopped": d.stopped_reason, "pages": len(d.pages), "flagged_for_person": flagged,
                             "hand_recall": cmp["recall"] if cmp else None, "wrong": cmp["wrong"] if cmp else [],
                             "seconds": round(time.perf_counter() - t0, 2)})
                if d.reached_confirmation:
                    drafts[f"{mapper}:{portal}"] = d.spec
                print(f"{mapper:8s} {portal:10s} {spc:18s} reached={d.reached_confirmation!s:5s} "
                      f"hand-recall={cmp['recall'] if cmp else '-'} flagged={flagged} {d.stopped_reason[:70]}")
    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M"), "rows": rows, "drafts": drafts}
    for mapper in mappers:
        r = [x for x in rows if x["mapper"] == mapper]
        out[f"summary:{mapper}"] = {
            "walks": len(r), "reached_confirmation": sum(x["reached"] for x in r),
            "hand_field_recall": round(sum(x["hand_recall"] for x in r if x["hand_recall"] is not None) /
                                       max(1, sum(x["hand_recall"] is not None for x in r)), 3),
            "wrong_mappings": sum(len(x["wrong"]) for x in r),
            "held_out_lakeshore": f"{sum(x['reached'] for x in r if x['portal'] == 'lakeshore')}/3"}
        print(mapper, out[f"summary:{mapper}"])
    rep = ROOT / "reports" / "autoconfig.json"
    rep.parent.mkdir(exist_ok=True)
    rep.write_text(json.dumps(out, indent=2, default=str))
    (ROOT / "app" / "assets").mkdir(parents=True, exist_ok=True)
    shutil.copy(rep, ROOT / "app" / "assets" / "autoconfig.json")
    print(f"wrote {rep}")


if __name__ == "__main__":
    main()
