"""LLM code paths tested with a fake model (no API key needed)."""
import json

from authops.agent.observe import FrameSnap, Observation
from authops.agent.policy import ClaudePolicy
from authops.docintel.extract import ClaudeExtractor
from authops.docintel.ocr import OCRDoc, OCRPage
from authops.llm import LLMResult
from authops.schemas import DocType
from authops.synth.generate import generate_cases
from authops.validation.rules import NLRule


class FakeLLM:
    model = "fake-model"

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts = []

    def complete(self, prompt, system="", images=None, max_tokens=1024):
        self.prompts.append(prompt)
        return LLMResult(self.reply, self.model, 1.0, tokens_in=100, tokens_out=10)


def _obs():
    return Observation("http://x/northwind/home", "Home", 200, [FrameSnap(0, "http://x", "Welcome", [
        {"i": 0, "tag": "a", "type": "", "id": "new-auth", "name": "", "label": "New Prior Authorization",
         "value": "", "occluded": False}], [], [], "Welcome")])


def _case():
    return generate_cases(1, seed=2)[0].model_dump(mode="json")


def test_claude_policy_accepts_allowed_tool_and_counts_tokens():
    llm = FakeLLM('{"tool": "click", "args": {"target": "New Prior Authorization"}, "reason": "start"}')
    act = ClaudePolicy("northwind", llm).next_action(_obs(), {"case": _case(), "files": ["a.pdf"]}, [])
    assert act["tool"] == "click" and act["_tokens"] == (100, 10)
    assert "PLAYBOOK" in llm.prompts[0] and "password" not in json.dumps(act).lower()


def test_claude_policy_rejects_tool_outside_allow_list():
    llm = FakeLLM('{"tool": "enter_totp", "args": {}}')  # not allowed on northwind
    act = ClaudePolicy("northwind", llm).next_action(_obs(), {"case": _case(), "files": []}, [])
    assert act["tool"] == "invalid"


def test_claude_extractor_caps_ungrounded_evidence():
    text = "Authorization Number: NWH-A-123456\nMember ID: NWH12345678"
    ocr = OCRDoc([OCRPage(text, [], 90.0)], 1.0)
    reply = json.dumps({
        "auth_number": {"value": "NWH-A-123456", "evidence": "Authorization Number: NWH-A-123456", "confidence": 0.95},
        "member_id": {"value": "NWH99999999", "evidence": "Member ID: NWH99999999", "confidence": 0.95},
    })
    ex = ClaudeExtractor(FakeLLM(reply)).extract("d1", ocr, DocType.APPROVAL_LETTER)
    assert ex.fields["auth_number"].confidence == 0.95 and not ex.fields["auth_number"].abstained
    assert ex.fields["member_id"].confidence <= 0.5 and ex.fields["member_id"].abstained  # evidence not in OCR


def test_nl_rule_strict_boolean_cast():
    case = generate_cases(1, seed=2)[0]
    doc = {"documents_text": "Goal 1: Knee flexion. Baseline: 60 degrees. Target: 110 degrees by week 12."}
    q = "Does each goal have a measurable baseline?"
    yes = '{"answer": true, "evidence": ["Baseline: 60 degrees. Target: 110 degrees"]}'
    assert NLRule(q, FakeLLM(yes)).run(case, doc).passed is True
    assert NLRule(q, FakeLLM('{"answer": false, "evidence": []}')).run(case, doc).passed is False
    # a bare word, a string "yes", or a YES with nothing quoted from the document never passes
    for reply in ("YES", "Probably yes", '{"answer": "yes"}', '{"answer": true, "evidence": []}'):
        assert NLRule(q, FakeLLM(reply)).run(case, doc).passed is None
