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


@pytest.mark.parametrize("portal,specialty", [("lakeshore", "aba"), ("lakeshore", "physical_therapy"),
                                              ("northwind", "behavioral_health"), ("keystone", "physical_therapy")])
def test_drafted_playbook_submits(portal, specialty, tmp_path):
    """A playbook drafted automatically from one sandbox walk drives the real browser agent."""
    from fastapi.testclient import TestClient

    from authops.agent.autoconfig import draft_playbook
    from authops.portals.app import create_app

    out = tmp_path / "corpus"
    cases = [c for c in generate_cases(60, seed=33, gap_rate=0.0) if c.specialty == specialty][:2]
    render_corpus(cases, out)
    chaos = Chaos(survey_modal_rate=1.0, summit_503_rate=0.0, summit_kick_rate=0.0)
    start = {"lakeshore": "/lakeshore/signin", "northwind": "/northwind/login", "keystone": "/keystone/login"}[portal]
    walker = TestClient(create_app(out / "cases.json", Chaos(survey_modal_rate=0.0)))
    draft = draft_playbook(walker, portal, start, CREDENTIALS[portal][1], cases[1].model_dump(mode="json"))
    assert draft.reached_confirmation, draft.stopped_reason
    exe = os.environ.get("AUTHOPS_CHROME") or ("/usr/bin/google-chrome" if Path("/usr/bin/google-chrome").exists() else None)
    with PortalServer(out / "cases.json", chaos) as srv, pw.sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox"], **({"executable_path": exe} if exe else {}))
        rt = AgentRuntime(b, srv.url, CredentialPool(CREDENTIALS, threshold=5), Store(tmp_path / "t.db"))
        c = cases[0]
        r = rt.run(c.model_dump(mode="json"), portal, PlaybookPolicy(portal, spec=draft.spec),
                   [str(out / "docs" / f"{c.case_id}_treatment_plan.pdf")])
        b.close()
        assert r.status == "submitted", (r.error_class, r.note)
        assert r.verified
        sub = srv.state.submissions[-1]
        assert sub["fields"]["member_id"] == c.patient.member_id
        assert sorted(sub["fields"]["cpt"]) == sorted(c.cpt_codes)


def test_portal_release_breaks_playbook_and_heal_recovers(tmp_path):
    """Northwind ships a redesign: the approved playbook fails; the healed candidate submits."""
    from fastapi.testclient import TestClient

    from authops.agent.heal import heal
    from authops.portals.app import create_app

    out = tmp_path / "corpus"
    cases = [c for c in generate_cases(60, seed=44, gap_rate=0.0) if c.specialty == "physical_therapy"][:2]
    render_corpus(cases, out)
    chaos = Chaos(survey_modal_rate=1.0, summit_503_rate=0.0, summit_kick_rate=0.0, northwind_release="v2")
    old = PlaybookPolicy("northwind")
    walker = TestClient(create_app(out / "cases.json", Chaos(survey_modal_rate=0.0, northwind_release="v2")))
    import yaml
    h = heal(yaml.safe_load((Path("playbooks") / "northwind.yaml").read_text()), walker, "northwind",
             "/northwind/login", CREDENTIALS["northwind"][1], cases[1].model_dump(mode="json"))
    assert h.status == "healed", h.stopped
    exe = os.environ.get("AUTHOPS_CHROME") or ("/usr/bin/google-chrome" if Path("/usr/bin/google-chrome").exists() else None)
    with PortalServer(out / "cases.json", chaos) as srv, pw.sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox"], **({"executable_path": exe} if exe else {}))
        rt = AgentRuntime(b, srv.url, CredentialPool(CREDENTIALS, threshold=5), Store(tmp_path / "t.db"))
        c = cases[0]
        doc = [str(out / "docs" / f"{c.case_id}_treatment_plan.pdf")]
        before = rt.run(c.model_dump(mode="json"), "northwind", old, doc)
        after = rt.run(c.model_dump(mode="json"), "northwind", PlaybookPolicy("northwind", spec=h.candidate), doc)
        b.close()
    assert before.status != "submitted"
    assert after.status == "submitted" and after.verified, (after.error_class, after.note)
