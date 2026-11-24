from dataclasses import dataclass, field

from authops.agent.validator import check


@dataclass
class Frame:
    elements: list = field(default_factory=list)


@dataclass
class Obs:
    url: str
    frames: list


def el(id_, label, tag="input"):
    return {"id": id_, "name": id_, "label": label, "tag": tag, "type": "text"}


OBS = Obs("http://portal.test/auth/new", [Frame([el("member_id", "Member ID"), el("dob", "Date of birth"),
                                                el("submit", "Submit request", "button")])])
CASE = {"patient": {"member_id": "KCM12345678", "dob": "2015-03-04", "last_name": "Osei"},
        "specialty": "aba", "cpt_codes": ["97153"], "icd10_codes": ["F84.0"], "requested_units": 120}
VALS = {"member_id": "KCM12345678", "dob": "2015-03-04"}
BASE = "http://portal.test"


def kinds(act, obs=OBS, history=()):
    return {f.kind for f in check(obs, act, CASE, VALS, list(history), BASE)}


def test_clean_action_passes():
    assert kinds({"tool": "fill", "args": {"target": "member_id", "value": "KCM12345678"},
                  "reason": "Fill the Member ID field"}) == set()
    assert kinds({"tool": "fill", "args": {"target": "Date of birth", "value": "03/04/2015"}}) == set()


def test_phantom_element_blocks():
    f = check(OBS, {"tool": "click", "args": {"target": "Attach clinical notes"}}, CASE, VALS, [], BASE)
    assert [x.kind for x in f] == ["phantom_target"] and f[0].blocking


def test_hallucinated_value_blocks():
    assert "unsourced_value" in kinds({"tool": "fill", "args": {"target": "member_id", "value": "KCM99999999"}})


def test_document_answer_counts_as_source():
    hist = [{"tool": "answer", "ok": True, "detail": "filled (answer 'VB-MAPP' from page 3)"}]
    assert "unsourced_value" not in kinds({"tool": "fill", "args": {"target": "member_id", "value": "VB-MAPP"}},
                                          history=hist)


def test_reason_contradicting_action_warns():
    f = check(OBS, {"tool": "fill", "args": {"target": "member_id", "value": "KCM12345678"},
                    "reason": "Enter the date of birth field"}, CASE, VALS, [], BASE)
    assert [x.kind for x in f] == ["reason_mismatch"] and not f[0].blocking


def test_leaving_the_portal_blocks():
    away = Obs("http://phish.example/login", OBS.frames)
    assert "off_domain" in kinds({"tool": "click", "args": {"target": "submit"}}, obs=away)
