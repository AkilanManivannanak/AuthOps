import json
import random
from pathlib import Path

from authops.assist.reader import check_plan, facts, read_letter
from authops.synth.generate import generate_cases
from authops.synth.render import render_letter, render_treatment_plan, save_doc


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    def complete(self, prompt, images=None, max_tokens=0, system=""):
        class R:
            pass
        r = R()
        r.text, r.model, r.latency_ms, r.cost_usd = json.dumps(self.payload), "fake", 10.0, 0.0
        return r


class Broken:
    def complete(self, *a, **k):
        raise RuntimeError("no network")


TEXT = """Keystone Community Medicaid
The determination is: DENIED.
Reason for denial:
Requested units exceed the per-request limit.
You may request a peer-to-peer review within 30 days of this notice."""


def test_rules_read_a_denial():
    r = read_letter([], text=TEXT)
    assert r["decision"] == "denied" and r["appeal_days"] == 30
    assert r["reason"].startswith("Requested units exceed")
    assert r["deadline"] == "within 30 days of the letter's date" and len(r["next_steps"]) == 3


def test_ai_quotes_are_checked_against_the_page_and_conflicts_flagged():
    ai = {"decision": "approved", "summary": "x", "next_steps": ["a", "b", "c"], "questions": [],
          "quotes": ["The determination is: DENIED", "approved for 40 visits"], "letter_date": "2026-11-01", "appeal_days": 30}
    r = read_letter([], llm=FakeLLM(ai), text=TEXT)
    assert [q["found"] for q in r["quotes"]] == [True, False]
    assert "conflict" in r and r["deadline"] == "by Dec 01, 2026"


def test_ai_failure_falls_back_to_rules():
    r = read_letter([], llm=Broken(), text=TEXT)
    assert r["layer"] == "rules" and r["ai_error"] == "RuntimeError" and r["decision"] == "denied"
    p = check_plan([], llm=Broken(), text=TEXT)
    assert p["layer"] == "rules" and any(c["name"] == "Medical necessity" for c in p["checks"])


def test_plan_check_flags_bad_npi_and_unsigned(tmp_path):
    t = "Treatment plan\nDiagnosis F84.0\nCPT 97153\nNPI 1234567890\nDates 01/02/2027 to 06/30/2027\nGoal 1 baseline 20%"
    p = check_plan([], text=t)
    by = {c["name"]: c["status"] for c in p["checks"]}
    assert by["Provider signature and date"] == "fix" and by["Provider NPI"] == "fix" and by["Diagnosis codes"] == "pass"


def test_ai_pass_without_a_real_quote_is_downgraded():
    ai = {"checks": [{"name": "Medical necessity", "status": "pass", "detail": "ok", "quote": "severe deficits in 12 areas"}],
          "missing": ["assessment"], "summary": "nearly"}
    p = check_plan([], llm=FakeLLM(ai), text="Plan signed /s/ Dr A. F84.0 97153 medical necessity is described.")
    mn = [c for c in p["checks"] if c["name"] == "Medical necessity"][0]
    assert mn["status"] == "unclear" and mn["found"] is False


def test_reads_a_rendered_letter(tmp_path):
    c = generate_cases(1, seed=6, gap_rate=0)[0]
    rng = random.Random(3)
    w, _, _ = render_letter(c, rng)
    r = read_letter([Path(p) for p in save_doc(w, tmp_path, "l", "scan", rng)])
    assert r["decision"] in ("approved", "partially approved", "denied") and r["start"] and r["end"]
    tp = save_doc(render_treatment_plan(c, rng, False), tmp_path, "t", "scan", rng)
    assert facts("F84.0 and 97153")["icd10"] == ["F84.0"]
    assert check_plan([Path(p) for p in tp])["score"] >= 70


def test_blank_signature_line_is_not_a_signature():
    assert facts("Provider Signature: ________ Date: ____")["signed"] is False
    assert facts("Provider Signature: /s/ Dana Whitfield, BCBA")["signed"] is True
    assert facts("Signature: Dana Whitfield")["signed"] is True
