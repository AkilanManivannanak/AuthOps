"""Synthetic long clinical charts for document-agent evaluation.

Silna's June 2026 engineering post names the limits of one-shot validation: charts over
100 pages, handwritten notes, rules that combine facts spread across a document, and
medical-necessity rules. This module builds charts that have exactly those properties,
with a known answer for every rule:

* key facts sit on pages scattered among dozens of daily session notes,
* distractors repeat the same kind of fact with the wrong value (an old assessment,
  a signature on a different form, a ruled-out diagnosis, an earlier hours figure),
* some rules need two pages to agree (diagnosis, hours, member ID),
* the medical-necessity rule needs the deficit, the intensity and the link between them.

Everything is synthetic. No real patient data is used or implied.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

RULES = {
    "R1_signature": "The treatment plan is signed by the rendering clinician and the signature is dated "
                    "within 30 days before the request date.",
    "R2_dx_consistent": "The ICD-10 code on the treatment plan matches the diagnosis on the diagnostic "
                        "evaluation.",
    "R3_units_consistent": "The units requested on the authorization request cover page match the units "
                           "on the treatment plan.",
    "R4_assessment_current": "A standardized assessment is documented and dated within 180 days before "
                             "the request date.",
    "R5_measurable_goals": "The treatment plan has at least 3 goals and every goal has a measurable "
                           "baseline and target.",
    "R6_specialty_requirement": "ABA: the plan includes a caregiver training goal. Physical therapy: at "
                                "least 4 weeks of a home exercise program are documented before this request.",
    "R7_member_id_consistent": "The member ID on the cover page matches the member ID on the treatment plan.",
    "R8_medical_necessity": "The plan explains why the requested intensity is needed by linking specific "
                            "documented deficits to the requested units (not a generic statement).",
}
CROSS_PAGE = {"R2_dx_consistent", "R3_units_consistent", "R7_member_id_consistent"}

SPEC = {
    "aba": dict(icd=["F84.0", "F84.5", "F88"], assess=("VB-MAPP", "milestones score"), unit="hours/week",
                units=(15, 35), cred="BCBA",
                deficits=["requests items with single words only", "elopes from instructional area 4-6 times per session",
                          "engages in self-injurious head hitting averaging 12 episodes per day",
                          "does not respond to name in 8 of 10 trials", "cannot complete a 3-step routine"],
                goals=["Mand for 20 preferred items", "Reduce head hitting", "Respond to name",
                       "Complete 3-step morning routine", "Tolerate transitions"]),
    "physical_therapy": dict(icd=["M54.50", "M25.561", "M17.11", "S83.511A"], assess=("LEFS", "score"),
                             unit="visits", units=(8, 24), cred="DPT",
                             deficits=["knee flexion limited to 85 degrees", "single-leg stance under 4 seconds",
                                       "cannot climb a flight of stairs without rails", "gait speed 0.7 m/s",
                                       "pain 7/10 with sit-to-stand"],
                             goals=["Knee flexion", "Single-leg stance", "Stair negotiation", "Gait speed",
                                    "Sit-to-stand pain"]),
}
FIRST = ["Maya", "Liam", "Ava", "Noah", "Zara", "Ethan", "Priya", "Lucas", "Amara", "Owen", "Hana", "Caleb"]
LAST = ["Okafor", "Brennan", "Castillo", "Nguyen", "Haddad", "Moreau", "Patel", "Kowalski", "Delgado", "Osei"]
CLIN = {"aba": "Dana Whitfield", "physical_therapy": "Samuel Ortiz"}

FILLER = [
    "Session began on time. Caregiver present for the first 10 minutes and reported a typical week at home.",
    "Data collected on target behaviors across natural environment teaching and discrete trials.",
    "Client transitioned between activities with one verbal prompt. Reinforcer preference assessment updated.",
    "Therapist modeled the skill, then faded prompts across trials. Generalization probes run with a novel item.",
    "No safety concerns noted today. Next session focuses on maintenance probes and the new program.",
    "Vitals within normal limits. Warm-up on the bike for 8 minutes before strengthening work.",
    "Manual therapy to the lateral joint line, followed by closed-chain strengthening.",
    "Patient tolerated the session well and reported soreness 3/10 afterwards, resolved before discharge.",
    "Home program reviewed. Patient demonstrated the exercises with correct form after one cue.",
    "Clinic schedule confirmed for next week. Insurance card re-scanned at the front desk.",
]


def _fmt(d: date) -> str:
    return d.strftime("%m/%d/%Y")


def _mid(n: int) -> str:
    return "".join(str((n * 7 + i * 3) % 10) for i in range(9))


@dataclass
class LongChart:
    chart_id: str
    specialty: str
    request_date: date
    pages: list[str]
    truth: dict[str, bool]            # rule_id -> True if the chart passes the rule
    key_pages: dict[str, list[int]]   # rule_id -> 1-based pages that hold the deciding facts
    handwritten: set[int] = field(default_factory=set)

    @property
    def n_pages(self) -> int:
        return len(self.pages)

    def text(self) -> str:
        return "\n\n".join(f"=== Page {i + 1} ===\n{p}" for i, p in enumerate(self.pages))


def _smudge(text: str, rng: random.Random, rate: float) -> str:
    swap = {"o": "0", "l": "1", "e": "c", "a": "o", "S": "5", "I": "l"}
    out = []
    for ch in text:
        out.append(swap[ch] if ch in swap and rng.random() < rate else ch)
    return "".join(out)


def make_chart(idx: int, n_pages: int, seed: int = 11, fail_rate: float = 0.3,
               today: date = date(2026, 11, 2)) -> LongChart:
    rng = random.Random(seed * 1000 + idx)
    specialty = "aba" if idx % 2 == 0 else "physical_therapy"
    s = SPEC[specialty]
    fails = {r for r in RULES if rng.random() < fail_rate}
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    member = "M" + _mid(idx + 3)
    req = today - timedelta(days=rng.randint(0, 20))
    dx = rng.choice(s["icd"])
    units = rng.randint(*s["units"])
    clin = CLIN[specialty]
    truth = {r: r not in fails for r in RULES}

    # cover page (always page 1)
    cover_units = units if "R3_units_consistent" not in fails else units + rng.choice([-5, 5, 10])
    cover_member = member if "R7_member_id_consistent" not in fails else member[:-2] + str((int(member[-2]) + 3) % 10) + member[-1]
    cover = (f"PRIOR AUTHORIZATION REQUEST\nRequest date: {_fmt(req)}\nPatient: {name}\nMember ID: {cover_member}\n"
             f"Service: {specialty.replace('_', ' ')}\nUnits requested: {cover_units} {s['unit']} for 26 weeks\n"
             f"Rendering clinician: {clin}, {s['cred']}")

    # diagnostic evaluation
    eval_dx = dx if "R2_dx_consistent" not in fails else rng.choice([c for c in s["icd"] if c != dx])
    deficits = rng.sample(s["deficits"], 3)
    evaluation = (f"DIAGNOSTIC EVALUATION\nPatient: {name}\nDiagnosis: {eval_dx}\nFindings: " +
                  "; ".join(deficits) + ".\nEvaluator: licensed clinician. Recommendation: services as medically necessary.")

    # standardized assessment
    if "R4_assessment_current" in fails:
        a_date = req - timedelta(days=rng.randint(200, 400))
    else:
        a_date = req - timedelta(days=rng.randint(10, 150))
    assess = (f"STANDARDIZED ASSESSMENT: {s['assess'][0]}\nPatient: {name}\nDate administered: {_fmt(a_date)}\n"
              f"Total {s['assess'][1]}: {rng.randint(20, 70)}\nAdministered by {clin}, {s['cred']}.")
    old_assess = (f"STANDARDIZED ASSESSMENT: {s['assess'][0]} (prior episode)\nPatient: {name}\nDate administered: "
                  f"{_fmt(req - timedelta(days=rng.randint(500, 800)))}\nTotal {s['assess'][1]}: {rng.randint(10, 40)}")

    # goals
    goal_names = rng.sample(s["goals"], 4 if rng.random() < 0.5 else 3)
    if "R5_measurable_goals" in fails:
        goal_lines = [f"Goal {i + 1}: {g}. Baseline: {rng.randint(5, 40)}%. Target: {rng.randint(70, 95)}% by week 26."
                      for i, g in enumerate(goal_names[:-1])]
        goal_lines.append(f"Goal {len(goal_names)}: Improve {goal_names[-1].lower()} as tolerated.")
    else:
        goal_lines = [f"Goal {i + 1}: {g}. Baseline: {rng.randint(5, 40)}%. Target: {rng.randint(70, 95)}% by week 26."
                      for i, g in enumerate(goal_names)]
    if specialty == "aba" and "R6_specialty_requirement" not in fails:
        goal_lines.append(f"Goal {len(goal_lines) + 1}: Caregiver training. Baseline: caregiver implements 2 of 10 "
                          "steps of the behavior plan. Target: 9 of 10 steps by week 26.")

    # medical necessity
    if "R8_medical_necessity" in fails:
        necessity = ("Medical necessity: The patient would benefit from continued services to make progress "
                     "toward goals.")
    else:
        necessity = (f"Medical necessity: Because the patient {deficits[0]} and {deficits[1]}, {units} {s['unit']} "
                     f"are required to deliver enough intervention trials to reach the targets in Goals 1 and 2.")

    # treatment plan (signature)
    if "R1_signature" in fails:
        mode = rng.choice(["blank", "stale"])
        sig = ("Signature: ______________\nDate signed: ________" if mode == "blank" else
               f"Signature: /s/ {clin}, {s['cred']}\nDate signed: {_fmt(req - timedelta(days=rng.randint(45, 120)))}")
    else:
        sig = f"Signature: /s/ {clin}, {s['cred']}\nDate signed: {_fmt(req - timedelta(days=rng.randint(1, 25)))}"
    plan = (f"TREATMENT PLAN\nPatient: {name}\nMember ID: {member}\nDiagnosis (ICD-10): {dx}\n"
            f"Requested: {units} {s['unit']}\n" + "\n".join(goal_lines) + f"\n{necessity}\n{sig}")

    # PT home exercise program history
    hep = None
    if specialty == "physical_therapy":
        weeks = rng.randint(1, 3) if "R6_specialty_requirement" in fails else rng.randint(4, 10)
        hep = (f"CONSERVATIVE CARE HISTORY\nPatient: {name}\nHome exercise program started "
               f"{_fmt(req - timedelta(weeks=weeks))} and continued for {weeks} weeks before this request. "
               f"Adherence reported as good.")

    # distractors: signed consent form, ruled-out diagnosis, earlier units figure
    distract = [
        f"CONSENT FOR TREATMENT\nPatient: {name}\nSignature: /s/ guardian\nDate signed: {_fmt(req - timedelta(days=3))}",
        f"Session note. Prior diagnosis {rng.choice(s['icd'])} was considered and ruled out at intake.",
        f"Session note. Initial discussion with family about {units + rng.choice([-8, 8])} {s['unit']}; plan to be "
        "finalized after assessment.",
    ]

    filler_count = max(0, n_pages - 5 - len(distract) - (1 if hep else 0))
    body = [old_assess] + distract + [
        f"DAILY SESSION NOTE {_fmt(req - timedelta(days=filler_count - i))}\nPatient: {name}\n" +
        " ".join(rng.sample(FILLER, 4)) for i in range(filler_count)]
    rng.shuffle(body)
    # place key pages at scattered positions
    keys = [("evaluation", evaluation), ("assessment", assess), ("plan", plan)] + ([("hep", hep)] if hep else [])
    for _, page in keys:
        body.insert(rng.randint(0, len(body)), page)
    pages = [cover] + body
    pos = {k: pages.index(p) + 1 for k, p in keys}

    key_pages = {
        "R1_signature": [pos["plan"]], "R2_dx_consistent": [pos["plan"], pos["evaluation"]],
        "R3_units_consistent": [1, pos["plan"]], "R4_assessment_current": [pos["assessment"]],
        "R5_measurable_goals": [pos["plan"]],
        "R6_specialty_requirement": [pos["hep"]] if hep else [pos["plan"]],
        "R7_member_id_consistent": [1, pos["plan"]], "R8_medical_necessity": [pos["plan"], pos["evaluation"]],
    }
    # handwritten-style notes: heavier smudging on a share of filler pages only, never on key pages
    hw = set()
    for i, p in enumerate(pages):
        if i + 1 not in pos.values() and i > 0 and rng.random() < 0.25:
            pages[i] = "[handwritten, scanned]\n" + _smudge(p, rng, 0.12)
            hw.add(i + 1)
    return LongChart(f"LC-{idx:03d}", specialty, req, pages, truth, key_pages, hw)


def make_corpus(lengths=(12, 30, 60, 100, 150), per_length: int = 6, seed: int = 11) -> list[LongChart]:
    out, idx = [], 0
    for n in lengths:
        for _ in range(per_length):
            out.append(make_chart(idx, n, seed=seed))
            idx += 1
    return out
