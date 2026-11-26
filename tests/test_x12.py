import json
from datetime import datetime

from authops.channels.x12 import build_278_request, build_278_response, parse_278_response, segments, validate_x12
from authops.synth.generate import generate_cases

NOW = datetime(2026, 11, 25, 9, 30)


def _case():
    c = generate_cases(1, seed=12, gap_rate=0.0)[0]
    return json.loads(c.model_dump_json())


def test_request_envelope_is_valid():
    x = build_278_request(_case(), ctrl=42, now=NOW)
    assert validate_x12(x) == []
    tags = [s[0] for s in segments(x)]
    assert tags[:4] == ["ISA", "GS", "ST", "BHT"] and tags[-3:] == ["SE", "GE", "IEA"]
    assert "SV1" in tags and "HI" in tags and "UM" in tags


def test_round_trip_approved_and_partial():
    case = _case()
    x = build_278_request(case, ctrl=7, now=NOW)
    r = parse_278_response(build_278_response(x, "approved", case["requested_units"], auth="AUTH991", now=NOW))
    assert r["decision"] == "approved" and r["auth_number"] == "AUTH991"
    assert r["approved_quantity"] == case["requested_units"] and r["member_id"] == case["patient"]["member_id"]
    p = parse_278_response(build_278_response(x, "partial", 10, auth="AUTH992", now=NOW))
    assert p["decision"] == "partial" and p["approved_quantity"] == 10 and p["start"] == case["start_date"]
    d = parse_278_response(build_278_response(x, "denied", reason="NME", now=NOW))
    assert d["decision"] == "denied" and d["reason_code"] == "NME" and d["approved_quantity"] is None
    assert validate_x12(build_278_response(x, "denied", now=NOW)) == []


def test_validator_catches_broken_files():
    x = build_278_request(_case(), ctrl=3, now=NOW)
    assert any("SE count" in e for e in validate_x12(x.replace("SE*", "SE*9", 1)))
    assert validate_x12("GS*HI~") == ["file must start with an ISA segment"]
    bad = x.replace("ABK:", "ABK:9", 1)
    assert any("diagnosis" in e for e in validate_x12(bad))


# ---- review fixes (Chrisen 3, 4): units, delimiters from the ISA, per-line decisions, escaping, an outside file
from pathlib import Path  # noqa: E402

GOLDEN = Path(__file__).parent / "fixtures" / "x12_278_response_golden.edi"


def test_sv1_uses_units_and_visits_go_in_hsd():
    c = _case()
    c["specialty"] = "physical_therapy"
    segs = segments(build_278_request(c, now=NOW))
    sv1 = [s for s in segs if s[0] == "SV1"]
    assert sv1 and all(s[3] == "UN" for s in sv1)
    assert any(s[0] == "HSD" and s[1] == "VS" for s in segs)
    bad = build_278_request(c, now=NOW).replace("**UN*", "**VS*", 1)
    assert any("SV103" in e for e in validate_x12(bad))


def test_golden_file_with_other_delimiters_and_mixed_lines():
    x = GOLDEN.read_text()
    assert validate_x12(x) == []
    r = parse_278_response(x)
    assert r["decision"] == "partial" and r["auth_number"] == "GSH-AUTH-5521"
    assert r["start"] == "2026-12-01" and r["end"] == "2027-05-31" and r["approved_quantity"] == 24
    assert r["member_id"] == "GSH9988776" and r["payor_id"] == "GSH01"
    lines = {ln["cpt"]: ln for ln in r["lines"]}
    assert lines["97110"]["decision"] == "approved" and lines["97110"]["auth_number"] == "GSH-AUTH-5521"
    assert lines["97035"]["decision"] == "denied" and lines["97035"]["reason_code"] == "NME"


def test_per_line_answers_round_trip():
    c = _case()
    x = build_278_request(c, now=NOW)
    cpts = c["cpt_codes"]
    if len(cpts) > 1:
        resp = build_278_response(x, "approved", auth="A9", now=NOW, lines={cpts[0]: "approved", cpts[1]: "denied"})
        r = parse_278_response(resp)
        assert r["decision"] == "partial" and [ln["decision"] for ln in r["lines"]][:2] == ["approved", "denied"]


def test_delimiters_in_data_are_removed_and_names_split():
    c = _case()
    c["patient"]["last_name"] = "O*NEIL"
    c["provider"] = {"name": "Samuel Ortiz, DPT", "npi": "1747938094"}
    x = build_278_request(c, now=NOW)
    assert validate_x12(x) == []
    nm = {s[1]: s for s in segments(x) if s[0] == "NM1"}
    assert nm["IL"][3] == "O NEIL" and nm["1P"][3:5] == ["ORTIZ", "SAMUEL"]
