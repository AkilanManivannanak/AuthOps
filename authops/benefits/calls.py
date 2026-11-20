"""Benefits-verification calls: transcripts, extraction, read-back, and patient cost estimates.

Silna's phone-agent post says voice models struggle with checklists and number sequences,
and that "a fluent wrong answer can delay a patient's care". For ABA, a phone call is often
the only accurate source of plan details. This module measures that failure mode directly:

* synthetic rep transcripts with the things real reps do: spell numbers out, correct
  themselves mid-sentence, answer with "remaining" instead of "met", describe what the plan
  pays instead of what the patient pays, and route behavioral health to a carve-out vendor;
* speech-recognition noise that swaps teens and tens ("fifteen" heard as "fifty");
* three extractors (naive, careful, careful + read-back) scored per field, with the
  dollar error each one causes in the patient's cost estimate.
"""
from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass

FIELDS = ["plan_active", "in_network", "deductible", "deductible_met", "coinsurance_pct", "copay",
          "oop_max", "oop_met", "visit_limit", "visits_used", "auth_required", "carve_out_vendor"]
VENDORS = ["Lighthouse Behavioral", "Beacon Path Health", "Clearview BH Partners"]

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
TEEN_TY = {"thirteen": "thirty", "fourteen": "forty", "fifteen": "fifty", "sixteen": "sixty",
           "seventeen": "seventy", "eighteen": "eighty", "nineteen": "ninety"}


def say(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else "-" + ONES[n % 10])
    if n < 1000:
        return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + say(n % 100))
    th, rest = divmod(n, 1000)
    if rest and rest % 100 == 0 and th < 10 and rng_style.random() < 0.5:
        return say(n // 100) + " hundred"     # "fifteen hundred"
    return say(th) + " thousand" + ("" if rest == 0 else " " + say(rest))


rng_style = random.Random(3)

WORD = {w: i for i, w in enumerate(ONES)} | {w: i * 10 for i, w in enumerate(TENS) if w}


def words_to_numbers(text: str) -> str:
    """Turn spelled-out amounts into digits: 'two thousand five hundred' -> '2500'."""
    toks = re.split(r"(\s+|-|,)", text)
    out, cur, total, active, pend = [], 0, 0, False, ""

    def flush():
        nonlocal cur, total, active, pend
        if active:
            out.append(str(total + cur) + pend)
        cur, total, active, pend = 0, 0, False, ""

    for t in toks:
        w = t.lower().strip()
        if w in WORD:
            cur += WORD[w]
            active, pend = True, ""
        elif w == "hundred" and active:
            cur, pend = (cur or 1) * 100, ""
        elif w == "thousand" and active:
            total += (cur or 1) * 1000
            cur, pend = 0, ""
        elif w in ("", "-") or (w == "and" and active) or t.isspace():
            if not active:
                out.append(t)
            else:
                pend += t
        else:
            flush()
            out.append(t)
    flush()
    return re.sub(r"(\d)\s+(?=\d)", r"\1 ", "".join(out))


@dataclass
class Benefits:
    plan_active: bool
    in_network: bool
    deductible: int
    deductible_met: int
    coinsurance_pct: int
    copay: int
    oop_max: int
    oop_met: int
    visit_limit: int | None
    visits_used: int
    auth_required: bool
    carve_out_vendor: str | None


def make_benefits(rng: random.Random, specialty: str) -> Benefits:
    ded = rng.choice([500, 1000, 1500, 2000, 2500, 3000, 3500])
    oop = ded + rng.choice([2000, 3000, 4000, 5000])
    copay_plan = rng.random() < 0.35
    limit = rng.choice([20, 30, 40, 60]) if specialty == "physical_therapy" else (None if rng.random() < 0.7 else 40)
    return Benefits(
        plan_active=rng.random() > 0.06, in_network=rng.random() > 0.1, deductible=ded,
        deductible_met=rng.choice([0, ded // 4, ded // 2, ded, ded * 3 // 4]),
        coinsurance_pct=0 if copay_plan else rng.choice([10, 15, 20, 30, 40]),
        copay=rng.choice([15, 30, 40, 50]) if copay_plan else 0, oop_max=oop,
        oop_met=rng.choice([0, 300, 900, 1500, 1800]), visit_limit=limit,
        visits_used=rng.randint(0, (limit or 40) - 1) if limit else 0,
        auth_required=rng.random() < (0.9 if specialty == "aba" else 0.5),
        carve_out_vendor=rng.choice(VENDORS) if specialty == "aba" and rng.random() < 0.3 else None)


QUESTIONS = {
    "plan_active": "Is the plan active today?",
    "in_network": "Is the provider in network?",
    "deductible": "What is the individual in-network deductible?",
    "deductible_met": "How much of the deductible has been met?",
    "coinsurance_pct": "What is the coinsurance for this service?",
    "copay": "Is there a copay per visit?",
    "oop_max": "What is the out-of-pocket maximum?",
    "oop_met": "How much of the out-of-pocket maximum has been met?",
    "visit_limit": "Is there a visit limit for this service?",
    "visits_used": "How many visits have been used this year?",
    "auth_required": "Is prior authorization required?",
    "carve_out_vendor": "Is behavioral health managed by a separate vendor?",
}


def rep_answer(field: str, b: Benefits, rng: random.Random) -> str:
    v = getattr(b, field)
    money = lambda n: say(n) + " dollars"  # noqa: E731
    if field == "plan_active":
        return "Yes, the plan is active." if v else "No, I'm showing that coverage terminated last month."
    if field == "in_network":
        return "Yes, they're in network." if v else "That provider is showing as out of network."
    if field in ("deductible", "oop_max"):
        if rng.random() < 0.3:
            wrong = v - rng.choice([500, 1000]) if v > 1000 else v + 500
            return f"It's {money(wrong)}, sorry, I mean {money(v)}."
        return f"It's {money(v)} for the calendar year."
    if field == "deductible_met":
        if rng.random() < 0.4:
            return f"They have {money(b.deductible - v)} remaining on the deductible."
        return f"{money(v)} has been met so far." if v else "Nothing has been met yet."
    if field == "oop_met":
        if rng.random() < 0.35:
            return f"There's {money(b.oop_max - v)} left to go on the out of pocket."
        return f"They've met {money(v)}." if v else "Nothing has been met yet."
    if field == "coinsurance_pct":
        if v == 0:
            return "No coinsurance, it's a copay plan."
        if rng.random() < 0.45:
            return f"The plan pays {say(100 - v)} percent after deductible."
        return f"Member pays {say(v)} percent after deductible."
    if field == "copay":
        return f"Yes, {money(v)} per visit." if v else "No copay, coinsurance applies."
    if field == "visit_limit":
        return (f"Yes, {say(v)} visits per calendar year, combined with OT and speech." if v
                else "No hard visit limit for this service.")
    if field == "visits_used":
        return f"They've used {say(v)} so far." if b.visit_limit else "No visits are being tracked against a limit."
    if field == "auth_required":
        return "Yes, prior auth is required." if v else "No auth needed for this one."
    if field == "carve_out_vendor":
        return (f"Yes, behavioral health is carved out to {v}, you'd need to call them." if v
                else "No, it's handled by us directly.")
    return ""


def asr(text: str, rng: random.Random, rate: float = 0.25) -> str:
    """Speech-recognition noise: teen/ty confusions."""
    def swap(m):
        w = m.group(0)
        if rng.random() < rate:
            return TEEN_TY.get(w, {v: k for k, v in TEEN_TY.items()}.get(w, w))
        return w
    return re.sub(r"\b(" + "|".join(list(TEEN_TY) + list(TEEN_TY.values())) + r")\b", swap, text)


@dataclass
class Call:
    call_id: str
    specialty: str
    truth: Benefits
    turns: list[tuple[str, str, str]]  # (field, question, what the agent heard)


def make_calls(n: int = 120, seed: int = 21, asr_rate: float = 0.25) -> list[Call]:
    rng = random.Random(seed)
    calls = []
    for i in range(n):
        spec = rng.choice(["aba", "physical_therapy", "behavioral_health"])
        b = make_benefits(rng, spec)
        turns = [(f, QUESTIONS[f], asr(rep_answer(f, b, rng), rng, asr_rate)) for f in FIELDS]
        calls.append(Call(f"BV-{i:03d}", spec, b, turns))
    return calls


# ------------------------------------------------------------------ extraction

def _nums(text: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", words_to_numbers(text))]


def extract_naive(call: Call) -> dict:
    """First number after the question. What a model that skims the transcript does."""
    out = {}
    for f, _, heard in call.turns:
        low, nums = heard.lower(), _nums(heard)
        if f in ("plan_active", "in_network", "auth_required"):
            out[f] = low.startswith("yes")
        elif f == "carve_out_vendor":
            out[f] = next((v for v in VENDORS if v.lower() in low), None)
        elif f == "visit_limit":
            out[f] = nums[0] if nums else None
        else:
            out[f] = nums[0] if nums else 0
    return out


def extract_careful(call: Call, partial: dict | None = None) -> dict:
    """Handles self-corrections, 'remaining' vs 'met', and plan-pays vs member-pays."""
    out = dict(partial or {})
    for f, _, heard in call.turns:
        low = heard.lower()
        if re.search(r"sorry|i mean|actually", low):
            low = re.split(r"sorry,? i mean|sorry|i mean|actually", low)[-1]
        nums = _nums(low)
        if f in ("plan_active", "in_network", "auth_required"):
            out[f] = low.strip().startswith("yes")
        elif f == "carve_out_vendor":
            out[f] = next((v for v in VENDORS if v.lower() in low), None)
        elif f == "coinsurance_pct":
            out[f] = 0 if "copay plan" in low else (100 - nums[0] if "plan pays" in low and nums else
                                                     nums[0] if nums else None)
        elif f == "deductible_met":
            ded = out.get("deductible")
            out[f] = (ded - nums[0] if "remaining" in low and nums and ded is not None else
                      nums[0] if nums else 0)
        elif f == "oop_met":
            mx = out.get("oop_max")
            out[f] = (mx - nums[0] if ("left" in low or "remaining" in low) and nums and mx is not None else
                      nums[0] if nums else 0)
        elif f == "visit_limit":
            out[f] = nums[0] if nums and "no hard" not in low else None
        elif f == "visits_used":
            out[f] = nums[0] if nums else 0
        else:
            out[f] = nums[0] if nums else 0
    return out


def readback(call: Call, values: dict, rng: random.Random, catch: float = 0.9) -> tuple[dict, int]:
    """Read every number back. The rep corrects a wrong value most of the time."""
    fixed, corrections = dict(values), 0
    for f in FIELDS:
        truth = getattr(call.truth, f)
        if fixed.get(f) != truth and rng.random() < catch:
            fixed[f] = truth
            corrections += 1
    return fixed, corrections


# ------------------------------------------------------------------ patient estimate

def estimate(b: dict | Benefits, allowed: float, visits: int) -> dict:
    """Patient responsibility for the next `visits` visits at an `allowed` amount each."""
    b = asdict(b) if isinstance(b, Benefits) else b
    if not b.get("plan_active", True):
        return {"patient_total": round(allowed * visits, 2), "note": "coverage inactive: self-pay"}
    if b.get("carve_out_vendor"):
        return {"patient_total": None, "note": f"carved out to {b['carve_out_vendor']}: verify with the vendor"}
    ded_left = max(0, (b.get("deductible") or 0) - (b.get("deductible_met") or 0))
    oop_left = max(0, (b.get("oop_max") or 0) - (b.get("oop_met") or 0))
    covered_left = None if b.get("visit_limit") in (None, 0) else max(0, b["visit_limit"] - (b.get("visits_used") or 0))
    total, uncovered = 0.0, 0
    for i in range(visits):
        if covered_left is not None and i >= covered_left:
            total += allowed
            uncovered += 1
            continue
        if b.get("copay"):
            pay = b["copay"]
        else:
            to_ded = min(allowed, ded_left)
            ded_left -= to_ded
            pay = to_ded + (allowed - to_ded) * (b.get("coinsurance_pct") or 0) / 100
        pay = min(pay, oop_left)
        oop_left -= pay
        total += pay
    note = "out of network: estimate uses in-network terms" if not b.get("in_network", True) else ""
    if uncovered:
        note = (note + "; " if note else "") + f"{uncovered} visits past the plan's visit limit"
    return {"patient_total": round(total, 2), "note": note}


def evaluate(calls: list[Call], allowed: float = 150.0, visits: int = 12, seed: int = 4) -> dict:
    rng = random.Random(seed)
    arms = {}
    for arm in ("naive", "careful", "careful_readback"):
        field_ok, wrong, est_err, perfect, corrections = 0, 0, [], 0, 0
        per_field = {f: 0 for f in FIELDS}
        for c in calls:
            if arm == "naive":
                v = extract_naive(c)
            else:
                v = extract_careful(c)
                if arm == "careful_readback":
                    v, k = readback(c, v, rng)
                    corrections += k
            ok = {f: v.get(f) == getattr(c.truth, f) for f in FIELDS}
            field_ok += sum(ok.values())
            wrong += sum(not x for x in ok.values())
            for f, x in ok.items():
                per_field[f] += x
            perfect += all(ok.values())
            t, e = estimate(c.truth, allowed, visits)["patient_total"], estimate(v, allowed, visits)["patient_total"]
            if t is not None and e is not None:
                est_err.append(abs(t - e))
        n = len(calls) * len(FIELDS)
        est_err.sort()
        arms[arm] = {"field_accuracy": round(field_ok / n, 3), "fluent_wrong_fields": wrong,
                     "calls_fully_correct": perfect, "calls": len(calls),
                     "estimate_abs_error_mean": round(sum(est_err) / len(est_err), 2) if est_err else 0,
                     "estimates_off_by_100_plus": sum(e >= 100 for e in est_err),
                     "per_field": {f: round(x / len(calls), 3) for f, x in per_field.items()},
                     "readback_corrections": corrections}
    return arms
