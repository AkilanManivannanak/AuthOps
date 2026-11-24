"""Phone agent for payors with no portal and no API (text simulation).

Silna's production phone agents run Twilio -> Deepgram STT -> LLM -> text
normalization -> ElevenLabs TTS. This module keeps the parts that decide whether a
call succeeds and can be tested without audio:

* an IVR menu tree driven by DTMF, plus a hold queue and a human rep simulator
* a chained agent: (transcript in) -> policy -> text normalization -> (speech out)
* normalization for speech: DOB spoken as a date, member IDs and NPIs digit by digit
* an ordered event timeline per call (what was heard, what was said, keypresses)
* ASR noise injection ("Cigna" heard as "signal") and keyword correction, the
  failure mode Silna called out for carrier names and CPT codes

Status checks and benefit checks are both supported. Their own post says eval and
A/B infrastructure for phone agents is still to be built; `run_call` returns a
structured result so calls can be scored like browser runs.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import date

DIGITS = "zero one two three four five six seven eight nine".split()
KEYWORDS = {"signal": "Cigna", "sig na": "Cigna", "a tna": "Aetna", "prairie valley": "Prairie Valley",
            "nine seven one five three": "97153"}


def speak_digits(s: str) -> str:
    return " ".join(DIGITS[int(c)] if c.isdigit() else c for c in s)


def normalize_for_speech(text: str) -> str:
    """Make text safe to read aloud: IDs digit by digit, dates spelled, abbreviations expanded."""
    text = re.sub(r"\bDOB\b", "date of birth", text)
    text = re.sub(r"\bNPI\b", "N P I", text)
    text = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b",
                  lambda m: date(int(m[1]), int(m[2]), int(m[3])).strftime("%B %-d, %Y"), text)
    text = re.sub(r"\b([A-Z]{3})(\d{8})\b", lambda m: " ".join(m[1]) + " " + speak_digits(m[2]), text)
    text = re.sub(r"\b(\d{10})\b", lambda m: speak_digits(m[1]), text)
    return text


def correct_asr(text: str) -> str:
    out = text
    for wrong, right in KEYWORDS.items():
        out = re.sub(wrong, right, out, flags=re.I)
    return out


@dataclass
class CallEvent:
    t: int
    kind: str  # heard | said | dtmf | hold | system
    text: str


@dataclass
class CallResult:
    case_id: str
    purpose: str
    status: str
    answer: dict = field(default_factory=dict)
    events: list[CallEvent] = field(default_factory=list)
    turns: int = 0


class PayorLine:
    """IVR + hold + rep. Knows the payor's auth records for status checks."""

    MENU = ("Thank you for calling Prairie Valley Health. For eligibility and benefits press 1. "
            "For prior authorization status press 2. For claims press 3.")

    def __init__(self, records: dict, rng: random.Random, asr_noise: float = 0.3):
        self.records = records
        self.rng = rng
        self.asr_noise = asr_noise
        self.state = "menu"
        self.purpose = None
        self.pending = None

    def _noisy(self, s: str) -> str:
        if self.rng.random() < self.asr_noise:
            s = s.replace("Prairie Valley", "prairie valley").replace("Cigna", "signal")
        return s

    def first(self) -> str:
        return self.MENU

    def respond(self, said: str | None, dtmf: str | None) -> str:
        if self.state == "menu":
            if dtmf in ("1", "2"):
                self.purpose = "benefits" if dtmf == "1" else "status"
                self.state = "hold"
                return "Please hold while we connect you to a representative."
            return "Sorry, I didn't get that. " + self.MENU
        if self.state == "hold":
            self.state = "rep"
            return self._noisy("Thanks for holding, this is Jordan with Prairie Valley. Can I get the member ID?")
        if self.state == "rep":
            m = re.search(r"([A-Z])\s([A-Z])\s([A-Z])\s((?:\w+\s?){8})", said or "")
            mid = None
            if m:
                letters = "".join(m.group(i) for i in (1, 2, 3))
                digits = "".join(str(DIGITS.index(w)) for w in m.group(4).split() if w in DIGITS)
                mid = letters + digits
            if not mid or mid not in self.records:
                return "I'm not finding that member. Could you repeat the member ID, slowly?"
            self.pending = mid
            self.state = "verify"
            return "And the patient's date of birth?"
        if self.state == "verify":
            rec = self.records[self.pending]
            spoken = date.fromisoformat(rec["dob"]).strftime("%B %-d, %Y")
            if spoken.lower() not in (said or "").lower():
                return "That date of birth doesn't match our records."
            self.state = "answer"
            if self.purpose == "status":
                return (f"I see the request. Status is {rec['status']}. Reference number "
                        f"{speak_digits(rec['ref'])}. Anything else?")
            return (f"The member is active. Outpatient therapy requires prior authorization. "
                    f"Copay is {rec['copay']} dollars per visit. Anything else?")
        return "Thank you for calling. Goodbye."


class PhoneAgent:
    """Rule-driven agent; the LLM version swaps `decide` for a model call with the same I/O."""

    def __init__(self, case: dict, purpose: str):
        self.case = case
        self.purpose = purpose
        self.retries = 0

    def decide(self, heard: str) -> tuple[str | None, str | None]:
        h = heard.lower()
        if "press 2" in h and "press 1" in h:
            return None, "2" if self.purpose == "status" else "1"
        if "member id" in h or "repeat the member" in h:
            self.retries += "repeat" in h
            return normalize_for_speech(f"The member ID is {self.case['patient']['member_id']}"), None
        if "please hold" in h:
            return None, None
        if "date of birth" in h:
            return normalize_for_speech(f"Date of birth is {self.case['patient']['dob']}"), None
        if "anything else" in h:
            return "No, that's everything. Thank you.", None
        return None, None


def parse_answer(heard: str, purpose: str) -> dict:
    out = {}
    if purpose == "status":
        m = re.search(r"Status is (\w+)", heard)
        out["status"] = m.group(1) if m else None
        m = re.search(r"Reference number ((?:\w+\s?)+?)\.", heard)
        if m:
            out["ref"] = "".join(str(DIGITS.index(w)) if w in DIGITS else w for w in m.group(1).split())
    else:
        m = re.search(r"Copay is (\d+) dollars", heard)
        out["copay"] = int(m.group(1)) if m else None
        out["pa_required"] = "requires prior authorization" in heard
    return out


def run_call(case: dict, purpose: str, records: dict, seed: int = 0, max_turns: int = 12,
             interrupt_rate: float = 0.0) -> CallResult:
    """`interrupt_rate`: chance the other side talks over the agent mid-reply. Only chunks whose
    play mark came back are logged as said; the rest are logged as dropped."""
    from authops.phone.stream import Playback

    rng = random.Random(seed)
    line = PayorLine(records, rng)
    agent = PhoneAgent(case, purpose)
    res = CallResult(case["case_id"], purpose, "in_progress")
    heard = line.first()
    for t in range(max_turns):
        heard = correct_asr(heard)
        res.events.append(CallEvent(t, "heard", heard))
        if "anything else" in heard.lower():
            res.answer = parse_answer(heard, purpose)
        said, dtmf = agent.decide(heard)
        if dtmf:
            res.events.append(CallEvent(t, "dtmf", dtmf))  # sent silently, never announced
        if said:
            pb = Playback()
            pb.say(said)
            while pb.queue:
                if len(pb.heard) >= 1 and rng.random() < interrupt_rate:
                    pb.interrupt()
                    break
                pb.mark()
            res.events.append(CallEvent(t, "said", pb.transcript()))
            if pb.dropped:
                res.events.append(CallEvent(t, "system", "interrupted; not heard: " + " ".join(pb.dropped)))
        if said and said.startswith("No, that's everything"):
            res.status = "completed" if all(v is not None for v in res.answer.values()) else "needs_human"
            res.turns = t + 1
            return res
        heard = line.respond(said, dtmf)
    res.status, res.turns = "needs_human", max_turns
    return res
