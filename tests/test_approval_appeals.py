"""Approval outlook and appeal packets."""
import random

import pytest

from authops.appeals.packet import build_packet, classify_reason, evaluate, make_denials, verify_letter
from authops.docagent.longdoc import make_corpus
from authops.intel.approval import ApprovalModel, Request, adjudicate, history_from, simulate
from authops.intel.approval import evaluate as approval_evaluate


@pytest.fixture(scope="module")
def model():
    reqs = simulate(n_weeks=30, per_week=100, seed=2)
    return ApprovalModel().fit(history_from(reqs, random.Random(3)))


def test_probability_falls_as_request_grows(model):
    r = Request(1, "KCM", "physical_therapy", 0.5, 0.9, False, 0.9, 30, 1.0)
    assert model.p_full(r, 8) > model.p_full(r, 30)


def test_recommendation_clears_target_and_never_exceeds_need(model):
    r = Request(1, "NWH", "aba", 0.6, 0.8, False, 0.9, 500, 1.0)
    q = model.recommend(r, 0.8)
    assert q <= r.need and model.p_full(r, q) >= 0.8


def test_true_process_denies_poor_documentation_and_cuts_overreach():
    r = Request(1, "SFB", "behavioral_health", 0.5, 0.9, False, 0.1, 20, 1.0)
    assert adjudicate(r, 5)[0] == "denied"
    r.doc_score = 0.9
    o, a = adjudicate(r, 200)
    assert o == "partial" and a < 200


def test_model_beats_fixed_haircut_on_both_axes():
    e = approval_evaluate(target=0.8)
    need, cut, mod = e["policies"]
    assert e["auc"] > 0.9
    assert mod["first_pass_full"] > cut["first_pass_full"] > need["first_pass_full"]
    assert mod["units_approved_first_pass"] > cut["units_approved_first_pass"]


def test_appeal_triage_and_citations():
    cs = make_corpus(lengths=(12, 60), per_length=4)
    by = {c.chart_id: c for c in cs}
    ds = make_denials(cs)
    for d in ds:
        assert classify_reason(d.letter) == d.rule
        p = build_packet(by[d.chart_id], d)
        assert (p.action == "appeal") == d.wrongful
        if p.action == "appeal":
            assert verify_letter(by[d.chart_id], p.letter)


def test_tampered_citation_is_caught():
    cs = make_corpus(lengths=(30,), per_length=2)
    by = {c.chart_id: c for c in cs}
    d = next(x for x in make_denials(cs) if x.wrongful)
    p = build_packet(by[d.chart_id], d)
    bad = p.letter.replace("Target:", "Target: 100% of", 1) if "Target:" in p.letter else p.letter.replace("/s/", "/s/ Dr.", 1)
    assert not verify_letter(by[d.chart_id], bad)


def test_appeals_evaluation_summary():
    e = evaluate()
    assert e["appeals_on_correct_denials"] == 0 and e["triage_accuracy"] == 1.0
