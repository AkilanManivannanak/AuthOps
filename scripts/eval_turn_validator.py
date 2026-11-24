"""Turn validator ablation: a policy that sometimes types a plausible wrong value, validator on vs off.

    python scripts/eval_turn_validator.py northwind 0.25     # 25% of typed values corrupted
    python scripts/eval_turn_validator.py keystone 0         # clean runs: counts false blocks

Needs Chromium (AUTHOPS_CHROME or a Playwright install).
Writes reports/turn_validator_<portal>_<p>.json.
"""
from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import playwright.sync_api as pw  # noqa: E402

from authops.agent.credentials import CredentialPool  # noqa: E402
from authops.agent.policy import PlaybookPolicy  # noqa: E402
from authops.agent.runtime import AgentRuntime  # noqa: E402
from authops.ops.store import Store  # noqa: E402
from authops.portals.app import Chaos  # noqa: E402
from authops.synth.generate import generate_cases  # noqa: E402
from authops.synth.render import render_corpus  # noqa: E402
from tests.test_e2e_portals import CREDENTIALS, PortalServer  # noqa: E402


class Hallucinating:
    """Wraps a policy and, with probability p, shifts the digits of a value it is about to type."""

    def __init__(self, inner, p: float, rng: random.Random):
        self.inner, self.p, self.rng = inner, p, rng
        self.start = inner.start
        self.injected = 0

    def __getattr__(self, k):
        return getattr(self.inner, k)

    def next_action(self, obs, ctx, history):
        a = self.inner.next_action(obs, ctx, history)
        args = a.get("args", {})
        if a.get("tool") == "fill" and "value" in args and self.rng.random() < self.p:
            v = str(args["value"])
            if any(ch.isdigit() for ch in v):
                bad = "".join(str((int(ch) + 3) % 10) if ch.isdigit() else ch for ch in v)
                a = dict(a, args=dict(args, value=bad))
                self.injected += 1
        return a


def main() -> None:
    portal = sys.argv[1] if len(sys.argv) > 1 else "northwind"
    p = float(sys.argv[2]) if len(sys.argv) > 2 else 0.25
    exe = os.environ.get("AUTHOPS_CHROME")
    out = ROOT / "data" / "validator_eval"
    cases = generate_cases(40, seed=21, gap_rate=0.0)
    render_corpus(cases, out)
    cases = cases[:20]
    res = {}
    for on in (False, True):
        rng = random.Random(7)
        wrong = sub = blocked = injected = verified = 0
        chaos = Chaos(survey_modal_rate=0.3, summit_503_rate=0, summit_kick_rate=0)
        with PortalServer(out / "cases.json", chaos) as srv, pw.sync_playwright() as play:
            b = play.chromium.launch(headless=True, args=["--no-sandbox"], **({"executable_path": exe} if exe else {}))
            for c in cases:
                n0 = len(srv.state.submissions)
                pol = Hallucinating(PlaybookPolicy(portal), p, rng)
                rt = AgentRuntime(b, srv.url, CredentialPool(CREDENTIALS, threshold=5),
                                  Store(out / f"ablation_{on}.db"), validate_turns=on)
                r = rt.run(c.model_dump(mode="json"), portal, pol,
                           [str(out / "docs" / f"{c.case_id}_treatment_plan.pdf")])
                injected += pol.injected
                blocked += r.counts.get("validator_block", 0)
                verified += bool(r.verified)
                if len(srv.state.submissions) > n0:
                    sub += 1
                    f = srv.state.submissions[-1]["fields"]
                    wrong += f.get("member_id") not in (None, c.patient.member_id) or (
                        "units" in f and str(f["units"]) != str(c.requested_units))
            b.close()
        res["validator_on" if on else "validator_off"] = {
            "cases": len(cases), "corrupted_fills": injected, "submitted": sub,
            "submitted_with_wrong_data": wrong, "verified": verified, "blocked_actions": blocked}
    print(json.dumps(res, indent=1))
    (ROOT / "reports" / f"turn_validator_{portal}_{p}.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
