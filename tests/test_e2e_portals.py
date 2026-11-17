"""End-to-end: playbook agent submits on all three sandbox portals and verifies the confirmation.

Needs a Chromium for Playwright (`python -m playwright install chromium`, or set AUTHOPS_CHROME).
"""
import os
from pathlib import Path

import pytest

from authops.agent.credentials import CredentialPool
from authops.agent.policy import PlaybookPolicy
from authops.agent.runtime import AgentRuntime
from authops.ops.store import Store
from authops.portals.app import CREDENTIALS, Chaos
from authops.portals.server import PortalServer
from authops.synth.generate import generate_cases
from authops.synth.render import render_corpus

pw = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    out = tmp_path_factory.mktemp("corpus")
    cases = [c for c in generate_cases(30, seed=21, gap_rate=0.0) if c.specialty == "aba"][:2]
    render_corpus(cases, out)
    return out, cases


@pytest.mark.parametrize("portal", ["northwind", "keystone", "summit"])
def test_playbook_agent_submits(env, portal, tmp_path):
    out, cases = env
    chaos = Chaos(survey_modal_rate=1.0, summit_503_rate=0.0, summit_kick_rate=0.0)
    exe = os.environ.get("AUTHOPS_CHROME") or ("/usr/bin/google-chrome" if Path("/usr/bin/google-chrome").exists() else None)
    with PortalServer(out / "cases.json", chaos) as srv, pw.sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox"], **({"executable_path": exe} if exe else {}))
        rt = AgentRuntime(b, srv.url, CredentialPool(CREDENTIALS, threshold=5), Store(tmp_path / "t.db"))
        c = cases[0]
        r = rt.run(c.model_dump(mode="json"), portal, PlaybookPolicy(portal),
                   [str(out / "docs" / f"{c.case_id}_treatment_plan.pdf")])
        b.close()
        assert r.status == "submitted", (r.error_class, r.note)
        assert r.verified
        sub = srv.state.submissions[-1]
        assert sub["fields"]["member_id"] == c.patient.member_id
        assert sorted(sub["fields"]["cpt"]) == sorted(c.cpt_codes)
