from datetime import date

from authops.agent.credentials import CredentialPool
from authops.channels.router import build_pas_bundle
from authops.docintel.evaluate import values_match
from authops.docintel.extract import _strip_leader, correct_cpt
from authops.docintel.normalize import npi_valid, norm_name, parse_date
from authops.ops.experiments import Arm, Experiment, QARamp
from authops.ops.scoring import smoothness
from authops.phone.ivr import correct_asr, normalize_for_speech
from authops.synth.generate import generate_cases, luhn_npi
from authops.validation.rules import load_requirements, validate_case

TODAY = date(2026, 11, 17)


def test_npi_checksum_roundtrip():
    npi = luhn_npi("123456789")
    assert npi_valid(npi)
    bad = npi[:-1] + str((int(npi[-1]) + 1) % 10)
    assert not npi_valid(bad)


def test_date_and_name_normalization():
    assert parse_date("March 3, 2026") == date(2026, 3, 3)
    assert parse_date("03/03/2026") == parse_date("2026-03-03")
    assert norm_name("FUJIMOTO, CALEB") == norm_name("Caleb Fujimoto")
    assert values_match("cpt_codes", ["97156", "97153"], ["97153", "97156"])


def test_ocr_debris_and_cpt_correction():
    assert _strip_leader("....4.4. 58AMDN70KG") == "58AMDN70KG"
    assert _strip_leader("0... ee cee eee RAHMAN, KAI") == "RAHMAN, KAI"
    codes, penalty = correct_cpt("37156")  # OCR misread 9 -> 3
    assert codes == ["97156"] and penalty < 1.0


def test_validation_catches_injected_gaps():
    cases = generate_cases(80, seed=3, today=TODAY, gap_rate=1.0)
    req = load_requirements()
    for c in cases:
        if not c.injected_gaps:
            continue
        rep = validate_case(c, TODAY, req, include_custom=False)
        assert not rep.ready, (c.case_id, c.injected_gaps)


def test_clean_cases_pass_default_rules():
    cases = generate_cases(40, seed=4, today=TODAY, gap_rate=0.0)
    req = load_requirements()
    blocked = [c for c in cases if not validate_case(c, TODAY, req, include_custom=False).ready]
    # only per-payor unit limits may block a clean case
    for c in blocked:
        rep = validate_case(c, TODAY, req, include_custom=False)
        assert {r.rule for r in rep.blocking} == {"units_within_payor_limit"}


def test_nl_rule_without_llm_routes_to_human():
    c = next(c for c in generate_cases(200, seed=5, today=TODAY, gap_rate=0.0)
             if c.payor.payor_id == "KCM" and c.specialty == "aba")
    rep = validate_case(c, TODAY, include_custom=True, documents_text="plan text")
    assert rep.needs_human and all(r.passed is None for r in rep.needs_human)


def test_credential_pool_disables_after_threshold():
    events = []
    pool = CredentialPool({"p": [{"username": "a", "password": "x"}, {"username": "b", "password": "y"}]},
                          threshold=2, on_disable=lambda c, w: events.append(c.username))
    a = pool.lease("p")
    pool.report(a, False)
    pool.report(a, False)
    assert a.disabled and events == [a.username]
    pool.release(a)
    b = pool.lease("p")
    assert b.username != a.username
    pool.release(b)
    assert pool.lease("p", exclude={b.username}) is None


def test_experiment_assignment_is_deterministic_and_weighted():
    exp = Experiment("e", [Arm("a", lambda p: None, 0.5), Arm("b", lambda p: None, 0.5)])
    ids = [f"PA-{i}" for i in range(400)]
    first = [exp.assign(i).name for i in ids]
    assert first == [exp.assign(i).name for i in ids]
    share = first.count("a") / len(first)
    assert 0.4 < share < 0.6


def test_qa_ramp_lowers_then_raises():
    ramp = QARamp(window=4, step=0.3)
    for _ in range(8):
        ramp.record("x", True, 95, False)
    assert ramp.state["x"].qa_share == 1.0  # 8/8 clean: lower bound 0.68, not enough evidence yet
    for _ in range(4):
        ramp.record("x", True, 95, False)
    assert ramp.state["x"].qa_share < 1.0   # 12/12: lower bound 0.76
    low = ramp.state["x"].qa_share
    for _ in range(4):
        ramp.record("x", True, 95, True)  # a silent error in the window
    assert ramp.state["x"].qa_share > low


def test_smoothness_penalties():
    assert smoothness({}, 10, 10) == 100
    assert smoothness({"loop": 1, "retry": 2}, 12, 10) == 100 - 25 - 8 - 2


def test_speech_normalization_and_asr_correction():
    s = normalize_for_speech("Member PRV12345678 DOB 2012-02-07 NPI 1234567893")
    assert "P R V one two three four five six seven eight" in s
    assert "February 7, 2012" in s and "N P I" in s
    assert correct_asr("I have signal on the line") == "I have Cigna on the line"


def test_fhir_pas_bundle_shape():
    c = generate_cases(1, seed=1, today=TODAY)[0].model_dump(mode="json")
    b = build_pas_bundle(c)
    claim = b["entry"][0]["resource"]
    assert claim["resourceType"] == "Claim" and claim["use"] == "preauthorization"
    assert [i["productOrService"]["coding"][0]["code"] for i in claim["item"]] == c["cpt_codes"]
