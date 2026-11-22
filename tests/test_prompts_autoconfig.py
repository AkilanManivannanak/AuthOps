"""Prompt registry and gate; automatic playbook drafting on the sandbox portals (no browser needed)."""
import json

import pyotp
import pytest
import yaml
from fastapi.testclient import TestClient

from authops.agent.autoconfig import compare, draft_playbook, lexicon_map, read_page
from authops.ops import prompts
from authops.portals.app import CREDENTIALS, Chaos, create_app
from authops.synth.generate import generate_cases


def test_registry_has_one_production_version_and_stable_fingerprints():
    live = prompts.production("extract")
    assert live.ref == "extract@v1"
    assert live.fingerprint == prompts.load("extract@v1").fingerprint
    assert prompts.load("extract@v2").fingerprint != live.fingerprint


def _run(rows_ok: dict[str, list[bool]], silent: float, acc: float):
    rows = [{"field": f, "ok": ok} for f, oks in rows_ok.items() for ok in oks]
    return {"summary": {"all": {"accuracy": acc, "silent_error": silent}}, "rows": rows}


def test_gate_blocks_critical_regression_and_silent_error_rise():
    base = _run({"member_id": [True] * 10, "notes": [True] * 5}, 0.02, 0.95)
    better = _run({"member_id": [True] * 10, "notes": [True] * 5}, 0.01, 0.97)
    worse = _run({"member_id": [True] * 8 + [False] * 2, "notes": [True] * 5}, 0.03, 0.96)
    assert prompts.gate(base, better, {"member_id"})["promote"]
    v = prompts.gate(base, worse, {"member_id"})
    assert not v["promote"] and any("member_id" in r for r in v["reasons"]) and any("silent" in r for r in v["reasons"])


def test_record_appends_traceable_entry(tmp_path):
    base, cand = prompts.load("extract@v1"), prompts.load("extract@v2")
    v = prompts.gate(_run({"a": [True]}, 0.0, 1.0), _run({"a": [True]}, 0.0, 1.0), set())
    e = prompts.record(base, cand, "ds123", v, log=tmp_path / "log.jsonl")
    line = json.loads((tmp_path / "log.jsonl").read_text().strip())
    assert line["candidate_fp"] == cand.fingerprint == e["candidate_fp"] and line["dataset"] == "ds123"


def test_lexicon_maps_unfamiliar_labels():
    p = read_page("""<form><label for=a>Subscriber number</label><input id=a name=a>
      <label for=b>Birthdate (MM/DD/YYYY)</label><input id=b name=b>
      <label for=c>Quantity (units)</label><input id=c name=c type=number>
      <label for=d>Service through</label><input id=d name=d type=date>
      <label for=e>Supporting documentation</label><input id=e name=e type=file>
      <button name=action value=draft>Save draft</button><button>Send</button></form>""", "/x")
    m = lexicon_map(p.fields)
    assert m == {"Subscriber number": "member_id", "Birthdate (MM/DD/YYYY)": "dob", "Quantity (units)": "units",
                 "Service through": "end", "Supporting documentation": "files"}


@pytest.fixture(scope="module")
def cases_file(tmp_path_factory):
    p = tmp_path_factory.mktemp("c") / "cases.json"
    p.write_text(json.dumps([c.model_dump(mode="json") for c in generate_cases(30)]))
    return p


@pytest.mark.parametrize("portal,start,specialty,expect", [
    ("northwind", "/northwind/login", "aba", True), ("keystone", "/keystone/login", "physical_therapy", True),
    ("keystone", "/keystone/login", "aba", False), ("summit", "/summit/login", "aba", False),
    ("lakeshore", "/lakeshore/signin", "aba", True)])
def test_drafts_reach_confirmation_or_flag_what_needs_a_person(cases_file, portal, start, specialty, expect):
    cases = json.loads(cases_file.read_text())
    case = next(c for c in cases if c["specialty"] == specialty)
    cred = CREDENTIALS[portal][0]
    totp = (lambda: pyotp.TOTP(cred["totp"]).now()) if "totp" in cred else None
    cl = TestClient(create_app(cases_file, Chaos(survey_modal_rate=0, summit_503_rate=0, summit_kick_rate=0)))
    d = draft_playbook(cl, portal, start, cred, case, totp=totp)
    assert d.reached_confirmation is expect, d.stopped_reason
    if not expect:   # stopped on fields a person must decide, and said which
        assert any(pg["unmapped"] for pg in d.pages)
    if portal in ("northwind", "keystone"):
        assert compare(yaml.safe_load(open(f"playbooks/{portal}.yaml")), d.spec)["recall"] == 1.0
