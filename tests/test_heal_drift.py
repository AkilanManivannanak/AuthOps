"""Self-healing playbooks and payor policy drift detection (no browser needed)."""
import json

import pytest
import yaml
from fastapi.testclient import TestClient

from authops.agent.autoconfig import draft_playbook
from authops.agent.heal import canary, fingerprint, heal
from authops.intel.drift import DEFAULT_CHANGES, Change, detect, evaluate, match, simulate_stream
from authops.portals.app import CREDENTIALS, Chaos, create_app
from authops.synth.generate import generate_cases


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    p = tmp_path_factory.mktemp("h") / "cases.json"
    cases = [c.model_dump(mode="json") for c in generate_cases(30, gap_rate=0.0)]
    p.write_text(json.dumps(cases))
    return p, next(c for c in cases if c["specialty"] == "physical_therapy")


def _client(p, rel=""):
    return TestClient(create_app(p, Chaos(survey_modal_rate=0, northwind_release=rel)))


@pytest.mark.parametrize("release,changed,status", [("", False, "no_change"), ("v2", True, "healed"),
                                                     ("v2-required", True, "needs_human")])
def test_canary_and_heal_by_release(env, release, changed, status):
    p, case = env
    cred = CREDENTIALS["northwind"][0]
    stored = fingerprint(draft_playbook(_client(p), "northwind", "/northwind/login", cred, case))
    now = draft_playbook(_client(p, release), "northwind", "/northwind/login", cred, case)
    assert canary(stored, now, "northwind").changed is changed
    h = heal(yaml.safe_load(open("playbooks/northwind.yaml")), _client(p, release), "northwind", "/northwind/login", cred, case)
    assert h.status == status
    if status == "healed":
        assert h.verified_in_sandbox and len(h.renamed) >= 8 and h.button == ["Submit Request", "Send for review"]
    if status == "needs_human":
        assert "Place of service" in h.added_unmapped and h.candidate is None


def test_heal_keeps_hand_written_judgment_steps(env):
    p, _ = env
    cases = json.loads(p.read_text())
    case = next(c for c in cases if c["specialty"] == "physical_therapy")
    old = yaml.safe_load(open("playbooks/keystone.yaml"))
    old["pages"][-1]["actions"][0][1]["target"] = "Medicaid Number"   # pretend the approved playbook used an old label
    h = heal(old, _client(p), "keystone", "/keystone/login", CREDENTIALS["keystone"][0], case)
    assert any("school schedule" in k for k in h.carried_over)


def test_drift_detects_planted_changes_and_proposes_correct_rules():
    s = simulate_stream(seed=1)
    m = match(detect(s), DEFAULT_CHANGES)
    got = {r["change"]: r for r in m["changes"]}
    assert got["unit_cap"]["delay_weeks"] == 0 and got["unit_cap"]["proposal_correct"]
    assert got["new_requirement"]["proposal_correct"] and got["turnaround"]["detected_week"] is not None


def test_drift_quiet_without_changes_and_volume_surge_is_not_a_policy_change():
    s = simulate_stream(seed=2, changes=[])
    alerts = detect(s)
    assert not [a for a in alerts if a.payor == "NWH" and a.specialty == "physical_therapy"]
    assert len(alerts) <= 2


def test_drift_evaluation_summary():
    e = evaluate(seeds=8)
    assert e["detection_rate"]["unit_cap"] == 1.0 and e["denials_before_rule"]["automatic"] < e["denials_before_rule"]["manual_6_weeks"]


def test_custom_change_cap_value_is_recovered():
    ch = [Change("unit_cap", "SFB", "aba", 9, 300, "ABA is limited to 300 units per authorization period.")]
    m = match(detect(simulate_stream(seed=5, changes=ch)), ch)
    assert m["changes"][0]["proposal_correct"]
