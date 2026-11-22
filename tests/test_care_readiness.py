"""Tests for the care-readiness features: long-chart validation, coverage monitoring,
benefits calls and cost estimates, case management, and the external API."""
from datetime import date, datetime, timedelta

import pytest

from authops.benefits.calls import Benefits, estimate, evaluate, make_calls, words_to_numbers
from authops.cases.manager import CaseManager
from authops.docagent.evaluate import score
from authops.docagent.longdoc import RULES, make_chart, make_corpus
from authops.docagent.validators import Finding, grounded, offline_agent, offline_oneshot
from authops.monitor.panel import compare, forecast


# ---- long charts
def test_chart_has_requested_length_and_key_pages():
    c = make_chart(3, 60)
    assert c.n_pages == 60
    for rule, pages in c.key_pages.items():
        assert rule in RULES and all(1 <= p <= 60 for p in pages)
    assert not (c.handwritten & {p for ps in c.key_pages.values() for p in ps})


def test_grounding_rejects_quote_not_on_page():
    c = make_chart(1, 20)
    f = grounded(c, Finding("R1_signature", "pass", [2], "this sentence is not in the chart anywhere"))
    assert f.verdict == "needs_human"


def test_offline_arms_score_and_oneshot_is_worse_on_long_charts():
    cs = make_corpus(lengths=(12, 150), per_length=4)
    s = score(cs, [offline_agent(c) for c in cs] + [offline_oneshot(c) for c in cs])
    assert s["offline_agent"]["summary"]["all"]["accuracy"] >= 0.95
    assert s["offline_oneshot"]["summary"]["100+ pages"]["coverage"] < s["offline_oneshot"]["summary"]["1-40 pages"]["coverage"]


# ---- monitoring
def test_proactive_monitor_beats_reactive():
    r = compare(n=80, seed=2)
    assert r["proactive"]["denied_dollars"] < r["scheduled"]["denied_dollars"] < r["reactive"]["denied_dollars"]


def test_forecast_flags_units_running_out_before_end_date():
    f = forecast(units_left=20, weekly_units=10, days_left=90, p90_business_days=12)
    assert f["binding_limit"] == "units" and f["start_reauth_now"] is True


# ---- benefits
def test_spoken_numbers():
    assert words_to_numbers("two thousand five hundred dollars") == "2500 dollars"
    assert words_to_numbers("fifteen hundred") == "1500"


def test_estimate_deductible_coinsurance_and_oop_cap():
    b = Benefits(True, True, 1000, 900, 20, 0, 1200, 1150, None, 0, True, None)
    # 100 deductible left on visit 1, then 20%; OOP left is only 50
    assert estimate(b, 150, 3)["patient_total"] == 50


def test_estimate_visit_limit_and_carve_out():
    b = Benefits(True, True, 0, 0, 0, 30, 5000, 0, 20, 19, False, None)
    assert estimate(b, 100, 3)["patient_total"] == 30 + 100 + 100
    b.carve_out_vendor = "Lighthouse Behavioral"
    assert estimate(b, 100, 3)["patient_total"] is None


def test_readback_reduces_fluent_wrong_answers():
    r = evaluate(make_calls(n=40))
    assert r["careful_readback"]["fluent_wrong_fields"] < r["careful"]["fluent_wrong_fields"] < r["naive"]["fluent_wrong_fields"]


# ---- cases
def test_case_sla_reminders_escalation_and_expiry():
    events = []
    m = CaseManager(on_event=lambda k, p: events.append(k))
    t0 = datetime(2026, 11, 2, 9)
    c = m.open("AU-1", "peer_to_peer", "aba", "P1", t0)
    assert c.state == "awaiting_clinician" and c.assignee
    acts = m.tick(t0 + timedelta(hours=40))
    assert {a["action"] for a in acts} >= {"reminder 50%", "reminder 80%", "escalated"}
    m.tick(t0 + timedelta(hours=49))
    assert c.state == "expired" and "case.expired" in events
    with pytest.raises(ValueError):
        m.respond(c.case_id, "too late", t0 + timedelta(hours=50))


# ---- API
def test_api_flow_idempotency_cases_and_signed_webhooks():
    from fastapi.testclient import TestClient

    from authops.api.app import create_app, verify_signature
    from authops.synth.generate import luhn_npi

    app = create_app(today=date(2026, 11, 2))
    cl = TestClient(app)
    H = {"X-API-Key": "demo-key"}
    assert cl.get("/v1/health").status_code == 200
    assert cl.post("/v1/authorizations", json={}, headers={"X-API-Key": "bad"}).status_code == 401
    hook = cl.post("/v1/webhooks", json={"url": "https://example.test/hook"}, headers=H).json()
    body = {"patient_first": "Ava", "patient_last": "Test", "dob": "2017-03-02", "member_id": "NWH12345678",
            "payor_id": "NWH", "specialty": "aba", "icd10_codes": ["F84.0"], "cpt_codes": ["97153"], "units": 120,
            "start_date": "2026-11-10", "end_date": "2027-05-10", "provider_name": "Dana Whitfield",
            "provider_npi": luhn_npi("123456789"), "signature_date": "2026-10-30"}
    r1 = cl.post("/v1/authorizations", json=body, headers={**H, "Idempotency-Key": "abc"}).json()
    r2 = cl.post("/v1/authorizations", json=body, headers={**H, "Idempotency-Key": "abc"}).json()
    assert r1["id"] == r2["id"] and r1["status"] == "ready_to_submit"
    unsigned = cl.post("/v1/authorizations", json={**body, "signature_date": None}, headers=H).json()
    assert unsigned["status"] == "needs_fixes" and any(i["rule"] == "signature_present" for i in unsigned["issues"])
    ev = cl.post(f"/v1/authorizations/{r1['id']}/events", json={"type": "peer_to_peer"}, headers=H).json()
    cid = ev["case"]["case_id"]
    assert ev["authorization"]["status"] == "action_required"
    assert cl.get("/v1/cases", headers=H).json()["queue"][0]["case_id"] == cid
    cl.post(f"/v1/cases/{cid}/respond", json={"response": "P2P booked for 2pm"}, headers=H)
    assert cl.get(f"/v1/authorizations/{r1['id']}", headers=H).json()["status"] == "pending_payor"
    d = app.state.deliveries[0]
    assert verify_signature(hook["secret"], d["body"], d["signature"])
    est = cl.post("/v1/benefit-estimates", json={"deductible": 500, "coinsurance_pct": 20, "oop_max": 3000,
                                                  "allowed_per_visit": 100, "visits": 10}, headers=H).json()
    assert est["patient_total"] == 500 + 0.2 * 500


def test_grounding_accepts_labeled_cross_page_quotes_but_not_changed_numbers():
    c = make_chart(0, 30)
    plan = c.key_pages["R3_units_consistent"][1]
    line = next(ln for ln in c.pages[plan - 1].split("\n") if ln.startswith("Requested:"))
    cover = next(ln for ln in c.pages[0].split("\n") if ln.startswith("Units requested:"))
    ok = Finding("R3_units_consistent", "pass", [1, plan], f"Cover page: {cover}. Treatment Plan: {line}")
    assert grounded(c, ok).verdict == "pass"
    n = int(line.split()[1])
    bad = Finding("R3_units_consistent", "pass", [plan], quotes=[line.replace(str(n), str(n + 7), 1)])
    assert grounded(c, bad).verdict == "needs_human"
