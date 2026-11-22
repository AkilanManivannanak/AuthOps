"""Appeal packets: from a denial letter and the chart to the right next action, with cited evidence.

After a denial a specialist has to answer one question before writing anything: is the payor
wrong, or is the chart actually missing what they asked for? Appealing a correct denial wastes
weeks and still fails; resubmitting when the evidence was there all along delays care for nothing.

For each denial this module:
  1. maps the denial reason to the payor rule it cites and the evidence that would rebut it;
  2. searches the chart for that evidence (deterministic finder offline, the background Claude
     document agent online), keeping only verdicts whose quotes are verbatim on the cited pages;
  3. triages: appeal (evidence present), corrective resubmission (evidence absent; lists the fix),
     or specialist review (evidence unclear);
  4. drafts the appeal letter from the cited quotes only, and re-checks every citation before the
     letter is offered for signature.

Denials are generated against synthetic charts with known answers, half wrongful (the chart meets
the rule) and half correct, so triage accuracy and citation validity are measurable.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from authops.docagent.longdoc import LongChart, make_corpus
from authops.docagent.validators import Finding, grounded, offline_agent

DENIAL_FOR_RULE = {
    "R1_signature": ("The treatment plan was not signed and dated by the rendering clinician within 30 days of the request.",
                     "Obtain the rendering clinician's signature and date on the treatment plan, then resubmit."),
    "R4_assessment_current": ("No standardized assessment completed within the last 180 days was submitted.",
                              "Administer the standardized assessment, add the scored results to the chart, then resubmit."),
    "R5_measurable_goals": ("Treatment goals do not include measurable baselines and targets.",
                            "Rewrite every goal with a measured baseline and a dated target, then resubmit."),
    "R6_specialty_requirement": ("Required specialty documentation (caregiver training goal for ABA, or at least four "
                                 "weeks of home exercise program for physical therapy) was not provided.",
                                 "Add the caregiver training goal (ABA) or document the home exercise program history (PT)."),
    "R8_medical_necessity": ("Medical necessity was not established for the requested intensity of services.",
                             "Add a medical-necessity statement that links the documented deficits to the requested units."),
    "R2_dx_consistent": ("The diagnosis on the treatment plan does not match the diagnostic evaluation.",
                         "Correct the diagnosis code on the treatment plan to match the evaluation, then resubmit."),
}
REF = "Reference"


@dataclass
class Denial:
    denial_id: str
    chart_id: str
    rule: str
    reason: str
    wrongful: bool           # answer key: True if the chart actually meets the rule
    letter: str


@dataclass
class Packet:
    denial_id: str
    action: str              # appeal | corrective_resubmission | specialist_review
    evidence: list[Finding] = field(default_factory=list)
    letter: str = ""
    fix: str = ""
    citations_valid: bool = True
    note: str = ""


def denial_letter(chart: LongChart, rule: str, rid: str) -> str:
    name = chart.pages[0].split("Patient: ")[1].split("\n")[0]
    member = chart.pages[0].split("Member ID: ")[1].split("\n")[0]
    return (f"NOTICE OF ADVERSE DETERMINATION\n{REF}: {rid}\nMember: {name} ({member})\n"
            f"Service: {chart.specialty.replace('_', ' ')}\nDetermination: Denied\n"
            f"Reason: {DENIAL_FOR_RULE[rule][0]}\n"
            "You may request reconsideration within 60 days by submitting documentation that addresses the reason above.")


def make_denials(charts: list[LongChart] | None = None, seed: int = 3) -> list[Denial]:
    rng = random.Random(seed)
    charts = charts or make_corpus()
    out = []
    for i, c in enumerate(charts):
        want_wrongful = i % 2 == 0
        rules = [r for r in DENIAL_FOR_RULE if c.truth[r] == want_wrongful] or list(DENIAL_FOR_RULE)
        rule = rng.choice(rules)
        rid = f"UM-{2026_0000 + i * 37}"
        out.append(Denial(f"DN-{i:03d}", c.chart_id, rule, DENIAL_FOR_RULE[rule][0], c.truth[rule],
                          denial_letter(c, rule, rid)))
    return out


def classify_reason(letter: str) -> str | None:
    """Map the free-text reason in a denial letter to the rule it cites."""
    m = re.search(r"Reason: (.+)", letter)
    text = (m.group(1) if m else letter).lower()
    keys = {"R1_signature": ["signed", "signature"], "R4_assessment_current": ["standardized assessment"],
            "R5_measurable_goals": ["measurable", "baseline"], "R6_specialty_requirement": ["caregiver", "home exercise"],
            "R8_medical_necessity": ["medical necessity"], "R2_dx_consistent": ["diagnosis"]}
    scores = {r: sum(k in text for k in ks) for r, ks in keys.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else None


def _draft(chart: LongChart, denial: Denial, f: Finding) -> str:
    name = chart.pages[0].split("Patient: ")[1].split("\n")[0]
    ref = re.search(rf"{REF}: (\S+)", denial.letter).group(1)
    quotes = f.quotes or [q.strip() for q in f.quote.split("|") if q.strip()]
    cites = "\n".join(f'  - "{q}" (chart page {p})' for q, p in zip(quotes, f.pages + f.pages[-1:] * 5))
    extra = ""
    if denial.rule == "R8_medical_necessity":
        ev = next((i + 1 for i, pg in enumerate(chart.pages) if pg.startswith("DIAGNOSTIC EVALUATION")), None)
        if ev:
            finding = chart.pages[ev - 1].split("Findings: ")[1].split("\n")[0]
            extra = f'\n  - "{finding.split(";")[0].strip()}" (chart page {ev})'
    return (f"Re: Request for reconsideration, determination {ref}\nMember: {name}\n\n"
            f"The determination states: \"{denial.reason}\"\n\n"
            "The submitted record already meets this requirement. The relevant documentation is quoted below with "
            f"its location in the enclosed chart:\n{cites}{extra}\n\n"
            "We request that the determination be reversed and the services authorized as requested. The complete "
            "chart is enclosed; the cited pages are flagged.\n\nRendering clinician signature: ____________  Date: ______")


def verify_letter(chart: LongChart, letter: str) -> bool:
    """Every quoted passage must appear on the page it cites."""
    for q, p in re.findall(r'"([^"]+)" \(chart page (\d+)\)', letter):
        if not grounded(chart, Finding("x", "pass", [int(p)], q)).verdict == "pass":
            return False
    return True


def build_packet(chart: LongChart, denial: Denial, finder: str = "offline", llm=None,
                 cache: dict | None = None) -> Packet:
    rule = classify_reason(denial.letter) or denial.rule
    if finder == "claude":
        from authops.docagent.validators import claude_agent
        key = chart.chart_id
        if cache is None or key not in cache:
            res = claude_agent(chart, llm)
            if cache is not None:
                cache[key] = res
        res = cache[key] if cache is not None else res
    else:
        res = offline_agent(chart)
    f = res.findings[rule]
    if f.verdict == "pass":
        letter = _draft(chart, denial, f)
        ok = verify_letter(chart, letter)
        if not ok:
            return Packet(denial.denial_id, "specialist_review", [f], letter, citations_valid=False,
                          note="a citation did not verify; a person must check the draft")
        return Packet(denial.denial_id, "appeal", [f], letter, citations_valid=True)
    if f.verdict == "fail":
        return Packet(denial.denial_id, "corrective_resubmission", [f], fix=DENIAL_FOR_RULE[rule][1],
                      note="the chart does not meet the requirement, so an appeal would not succeed")
    return Packet(denial.denial_id, "specialist_review", [f], note=f.reason or "evidence unclear")


def evaluate(finder: str = "offline", llm=None, charts: list[LongChart] | None = None) -> dict:
    charts = charts or make_corpus()
    by_id = {c.chart_id: c for c in charts}
    denials = make_denials(charts)
    cache: dict = {}
    rows = []
    for d in denials:
        c = by_id[d.chart_id]
        p = build_packet(c, d, finder, llm, cache)
        right = (p.action == "appeal") == d.wrongful if p.action != "specialist_review" else None
        cited = {pg for f in p.evidence for pg in f.pages}
        rows.append({"denial": d.denial_id, "rule": d.rule, "pages": c.n_pages, "wrongful": d.wrongful,
                     "action": p.action, "correct": right, "citations_valid": p.citations_valid,
                     "cites_key_page": bool(cited & set(c.key_pages[d.rule])) if p.action == "appeal" else None})
    n = len(rows)
    decided = [r for r in rows if r["correct"] is not None]
    appeals = [r for r in rows if r["action"] == "appeal"]
    return {"finder": finder, "denials": n, "wrongful": sum(r["wrongful"] for r in rows),
            "triage_accuracy": round(sum(r["correct"] for r in decided) / max(1, len(decided)), 3),
            "to_specialist": n - len(decided),
            "appeals_on_correct_denials": sum(not r["wrongful"] for r in appeals),
            "wrongful_denials_not_appealed": sum(r["wrongful"] and r["action"] != "appeal" for r in rows),
            "appeal_letters_with_valid_citations": f"{sum(r['citations_valid'] for r in appeals)}/{len(appeals)}",
            "appeals_citing_the_deciding_page": f"{sum(bool(r['cites_key_page']) for r in appeals)}/{len(appeals)}",
            "rows": rows}
