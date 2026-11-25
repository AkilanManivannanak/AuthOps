"""Shapes learned from a real outpatient PT clinic's paperwork. All names and numbers here are invented."""
from datetime import date

from authops.assist.reader import (_icd_fix, check_plan, insurances, modality_codes, referral, send_auth_to)

REFERRAL = """To Whom It May Concern,
PT
Please evaluate patient for the following reason
Referral Reason:
Lew back pain, unspecified (MS4.50}
Patient Demographic:
Name: DOE, JANE  Gender: Female
First Insurance: BCBS Dual Advantage (Self) Insured: DOE, JANE InsuredID: XYZ000000
Secondary Insurance: MEDICAID (Self) Insured: DOE, JANE InsuredID: AB00000C
Third Insurance: MEDICARE (Self) Insured: DOE, JANE InsuredID: 0AA0AA0AA00
Past Medical History:
(1) Hyperlipidemia (E78.2)
(2) Type 2 diabetes mellitus with other specified complication (E11.69)
(3) Bilateral primary osteoarthritis of knee (M17.0)
"""

VISIT_LOG = """TREATMENT RECORD
PATIENT FULL NAME SEX: M F
CP: cold packs HP: hot packs US: ultra sound TX: traction PB: paraffin bath
TM: tread mill MR: myo fascial release AE: active assist EX. TE: therapeutic EX."""


def test_ocr_repair_inside_icd_codes():
    assert _icd_fix("MS4.50}") == "M54.50" and _icd_fix("G3O.0") == "G30.0"


def test_referral_reason_beats_the_problem_list():
    r = referral(REFERRAL)
    assert r["code"] == "M54.50" and r["reason"].lower().endswith("unspecified")
    assert r["discipline"] == "physical therapy" and r["other_codes"] == 3


def test_three_insurances_and_who_gets_the_request():
    ins = insurances(REFERRAL)
    assert [i["payor"] for i in ins] == ["Anthem Blue Cross and Blue Shield", "Medicaid", "Medicare"]
    assert ins[0]["medicare_advantage"] and not ins[1]["medicare_advantage"]
    to = send_auth_to(ins)
    assert to["payor"] == "Anthem Blue Cross and Blue Shield" and to["dual_eligible"]
    assert any("Original Medicare" in n for n in to["notes"]) and any("member IDs" in n for n in to["notes"])


def test_a_referral_is_not_scored_like_a_plan():
    r = check_plan([], None, text=REFERRAL, today=date(2026, 11, 25))
    assert r["kind"] == "referral" and r["score"] < 50 and r["to_fix"] >= 4
    assert any("97161" in m for m in r["missing"])
    assert "Provider signature and date" not in [c["name"] for c in r["checks"]]


def test_visit_log_columns_map_to_billing_codes():
    m = {x["column"]: x["cpt"] for x in modality_codes(VISIT_LOG)}
    assert m["US"] == "97035" and m["MR"] == "97140" and m["TX"] == "97012" and m["PB"] == "97018" and m["TE"] == "97110"
    r = check_plan([], None, text=VISIT_LOG)
    assert r["kind"] == "visit_log" and "authorization number" in r["missing"][0]


def test_plain_plans_are_unchanged():
    assert referral("Treatment plan. Goals: walk 100 ft. Signed by: A. Therapist") is None
    assert modality_codes("Treatment plan with goals and baseline") == []
