"""Synthetic prior-authorization cases.

All payors, providers and patients are fictional. Nothing here is real PHI. The
generator is seeded so every report in this repo is reproducible.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from authops.schemas import Case, Patient, Payor, Provider

PAYORS = [
    Payor(payor_id="NWH", name="Northwind Health Plan", plan_type="commercial",
          channel="portal", portal_id="northwind", letter_template="a"),
    Payor(payor_id="KCM", name="Keystone Community Medicaid", plan_type="medicaid_mco",
          channel="portal", portal_id="keystone", letter_template="b"),
    Payor(payor_id="SFB", name="Summit Federal Benefits", plan_type="federal",
          channel="portal", portal_id="summit", letter_template="c"),
    Payor(payor_id="HBL", name="Harborline Health", plan_type="commercial",
          channel="fhir", portal_id=None, letter_template="a"),
    Payor(payor_id="PRV", name="Prairie Valley Health", plan_type="commercial",
          channel="phone", portal_id=None, letter_template="b"),
]
PAYOR_BY_ID = {p.payor_id: p for p in PAYORS}

# Specialty -> (ICD-10 pool, CPT pool, units range, frequency options)
SPECIALTIES = {
    "aba": (["F84.0", "F84.5", "F88"], ["97153", "97155", "97156"], (80, 480),
            ["20 hrs/week", "25 hrs/week", "30 hrs/week"]),
    "physical_therapy": (["M54.50", "M25.561", "S83.511A", "M17.11"], ["97110", "97140", "97530"],
                         (8, 36), ["2x/week", "3x/week"]),
    "behavioral_health": (["F41.1", "F32.1", "F43.10"], ["90837", "90834", "90847"], (6, 24),
                          ["1x/week", "2x/month"]),
}

FIRST = ["Maya", "Liam", "Ava", "Noah", "Zara", "Ethan", "Priya", "Lucas", "Amara", "Owen",
         "Sofia", "Mateo", "Hana", "Caleb", "Leah", "Rohan", "Ines", "Felix", "Nora", "Kai"]
LAST = ["Okafor", "Brennan", "Castillo", "Nguyen", "Haddad", "Lindqvist", "Moreau", "Patel",
        "Kowalski", "Abernathy", "Delgado", "Fujimoto", "Osei", "Varga", "Whitlock", "Rahman"]
PRACTICES = [
    ("Brightpath Therapy Group", "Dana Whitfield, BCBA"),
    ("Riverside Movement PT", "Samuel Ortiz, DPT"),
    ("Clearwater Behavioral Health", "Alicia Moreno, LCSW"),
]
SPECIALTY_PRACTICE = {"aba": 0, "physical_therapy": 1, "behavioral_health": 2}

GAP_TYPES = ["missing_signature", "expired_plan", "invalid_icd10", "cpt_specialty_mismatch",
             "missing_school_schedule"]


def luhn_npi(base9: str) -> str:
    """NPI check digit: Luhn over '80840' + first 9 digits."""
    digits = [int(d) for d in "80840" + base9]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    check = (10 - (total % 10)) % 10
    return base9 + str(check)


def make_provider(rng: random.Random, specialty: str) -> Provider:
    practice, name = PRACTICES[SPECIALTY_PRACTICE[specialty]]
    npi = luhn_npi("1" + "".join(str(rng.randint(0, 9)) for _ in range(8)))
    tax = f"{rng.randint(10, 99)}-{rng.randint(1000000, 9999999)}"
    return Provider(name=name, npi=npi, practice=practice, tax_id=tax)


def make_case(rng: random.Random, idx: int, today: date, gap_rate: float = 0.3) -> Case:
    specialty = rng.choice(list(SPECIALTIES))
    icd_pool, cpt_pool, (u_lo, u_hi), freqs = SPECIALTIES[specialty]
    payor = rng.choice(PAYORS)
    dob = date(rng.randint(2008, 2021) if specialty == "aba" else rng.randint(1955, 2005),
               rng.randint(1, 12), rng.randint(1, 28))
    patient = Patient(
        patient_id=f"P{idx:04d}", first_name=rng.choice(FIRST), last_name=rng.choice(LAST), dob=dob,
        member_id=f"{payor.payor_id}{rng.randint(10_000_000, 99_999_999)}",
    )
    start = today + timedelta(days=rng.randint(3, 21))
    end = start + timedelta(days=rng.choice([90, 120, 180]))
    case = Case(
        case_id=f"PA-{idx:04d}", patient=patient, provider=make_provider(rng, specialty), payor=payor,
        specialty=specialty,
        icd10_codes=rng.sample(icd_pool, k=rng.randint(1, min(2, len(icd_pool)))),
        cpt_codes=rng.sample(cpt_pool, k=rng.randint(1, 2)),
        requested_units=rng.randint(u_lo, u_hi), frequency=rng.choice(freqs),
        start_date=start, end_date=end,
        signature_present=True, signature_date=today - timedelta(days=rng.randint(1, 20)),
        school_schedule_attached=(specialty == "aba" and payor.plan_type == "medicaid_mco"),
    )
    if rng.random() < gap_rate:
        gap = rng.choice(GAP_TYPES)
        case.injected_gaps.append(gap)
        if gap == "missing_signature":
            case.signature_present, case.signature_date = False, None
        elif gap == "expired_plan":
            case.end_date = today - timedelta(days=rng.randint(1, 30))
            case.start_date = case.end_date - timedelta(days=90)
        elif gap == "invalid_icd10":
            case.icd10_codes = ["F8A.0"]
        elif gap == "cpt_specialty_mismatch":
            other = [s for s in SPECIALTIES if s != specialty]
            case.cpt_codes = [SPECIALTIES[rng.choice(other)][1][0]]
        elif gap == "missing_school_schedule":
            if specialty == "aba" and payor.plan_type == "medicaid_mco":
                case.school_schedule_attached = False
            else:
                case.injected_gaps.remove(gap)
    return case


def generate_cases(n: int = 60, seed: int = 7, today: date | None = None,
                   gap_rate: float = 0.3) -> list[Case]:
    rng = random.Random(seed)
    today = today or date(2026, 11, 17)
    return [make_case(rng, i + 1, today, gap_rate) for i in range(n)]


def payor_decision(case: Case, rng: random.Random) -> tuple[str, int, str | None]:
    """Simulated payor adjudication: returns (decision, approved_units, denial_reason)."""
    if case.injected_gaps:
        reasons = {
            "missing_signature": "Treatment plan is not signed by the rendering provider.",
            "expired_plan": "Submitted treatment plan dates have expired.",
            "invalid_icd10": "Diagnosis code is invalid or not billable.",
            "cpt_specialty_mismatch": "Requested service is not consistent with the diagnosis.",
            "missing_school_schedule": "School schedule required for ABA hours during school days.",
        }
        return "denied", 0, reasons[case.injected_gaps[0]]
    from authops.validation.rules import load_requirements

    spec = load_requirements()["payors"][case.payor.payor_id]["specialties"][case.specialty]
    if case.requested_units > spec.get("max_units_per_request", 10**9):
        return "denied", 0, "Requested units exceed the per-request limit."
    # Hidden policy change our requirements DB has not picked up yet (requirements drift):
    # Keystone tightened PT to 20 visits per request in an October bulletin.
    if case.payor.payor_id == "KCM" and case.specialty == "physical_therapy" and case.requested_units > 20:
        return "denied", 0, "Physical therapy is limited to 20 visits per authorization period."
    if rng.random() < 0.2:
        return "partial", max(1, int(case.requested_units * rng.choice([0.5, 0.75]))), None
    return "approved", case.requested_units, None
