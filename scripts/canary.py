"""Daily portal canary: walk each sandbox portal, compare page fingerprints with the approved ones.

    python scripts/canary.py                 # check; writes reports/canary.json
    python scripts/canary.py --approve       # store today's fingerprints as approved
    python scripts/canary.py --release v2    # simulate a Northwind redesign and attempt a heal
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pyotp  # noqa: E402
import yaml  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from authops.agent.autoconfig import draft_playbook  # noqa: E402
from authops.agent.heal import canary, heal, save_fingerprint, stored_fingerprint  # noqa: E402
from authops.portals.app import CREDENTIALS, Chaos, create_app  # noqa: E402
from authops.synth.generate import generate_cases  # noqa: E402

STARTS = {"northwind": "/northwind/login", "keystone": "/keystone/login", "lakeshore": "/lakeshore/signin"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--release", default="")
    args = ap.parse_args()
    cases = [c.model_dump(mode="json") for c in generate_cases(30, seed=8, gap_rate=0.0)]
    cf = Path(tempfile.mkdtemp()) / "cases.json"
    cf.write_text(json.dumps(cases))
    case = next(c for c in cases if c["specialty"] == "physical_therapy")
    out = {"ts": time.strftime("%Y-%m-%d %H:%M"), "release": args.release or "current", "portals": {}}
    for portal, start in STARTS.items():
        cred = CREDENTIALS[portal][0]
        totp = (lambda c=cred: pyotp.TOTP(c["totp"]).now()) if "totp" in cred else None
        mk = lambda: TestClient(create_app(cf, Chaos(survey_modal_rate=0, northwind_release=args.release)))  # noqa: E731
        d = draft_playbook(mk(), portal, start, cred, case, totp=totp)
        if args.approve:
            save_fingerprint(portal, d)
            out["portals"][portal] = {"approved": True}
            continue
        stored = stored_fingerprint(portal)
        res = canary(stored or {}, d, portal)
        row = {"changed": res.changed, "pages": res.pages}
        if res.changed and (ROOT / "playbooks" / f"{portal}.yaml").exists():
            h = heal(yaml.safe_load((ROOT / "playbooks" / f"{portal}.yaml").read_text()), mk(), portal, start, cred, case,
                     totp=totp)
            row["heal"] = {"status": h.status, "renamed": h.renamed, "needs_human": h.added_unmapped,
                           "removed": h.removed, "button": h.button, "verified_in_sandbox": h.verified_in_sandbox}
        out["portals"][portal] = row
        print(portal, "changed" if res.changed else "unchanged", row.get("heal", {}).get("status", ""))
    if not args.approve:
        (ROOT / "reports" / "canary.json").write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
