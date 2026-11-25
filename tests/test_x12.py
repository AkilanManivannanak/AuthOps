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
