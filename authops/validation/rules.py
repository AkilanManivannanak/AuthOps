"""Pre-submission document validation (rules engine).

Design follows the pattern Silna published for Predictive Document Intelligence:

* A rule is a boolean predicate. Default rules are deterministic code (expiry,
  ICD-10 validity, NPI checksum). Custom rules are plain-English questions an LLM
  must answer strictly yes or no, cast to bool; anything else counts as a failure
  to evaluate, never as a pass.
* Configurations bundle rules (AND). A configuration process is a small directed
  graph whose edges are gating conditions (document type, payor, specialty); a
  document walks one path and collects the rules on it.
* The point is to catch denials before the payor does. `validate_case` returns the
  failing rules with a human-readable fix, which is what an intake coordinator acts on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import yaml

from authops.docintel.normalize import SPECIALTY_CPT, icd10_valid, npi_valid
from authops.schemas import Case

REQ_PATH = Path(__file__).resolve().parents[2] / "configs" / "payor_requirements.yaml"


@dataclass
class RuleResult:
    rule: str
    passed: bool | None  # None = could not evaluate (routes to a human)
    message: str = ""
    kind: str = "default"


@dataclass
class Rule:
    name: str
    check: Callable[[Case, dict], bool]
    fix: str
    kind: str = "default"

    def run(self, case: Case, ctx: dict) -> RuleResult:
        try:
            ok = bool(self.check(case, ctx))
        except Exception as e:  # a crashing rule must not pass silently
            return RuleResult(self.name, None, f"rule error: {e}", self.kind)
        return RuleResult(self.name, ok, "" if ok else self.fix, self.kind)


DEFAULT_RULES: dict[str, Rule] = {r.name: r for r in [
    Rule("signature_present", lambda c, x: c.signature_present and c.signature_date is not None,
         "Treatment plan must be signed and dated by the rendering provider."),
    Rule("plan_not_expired", lambda c, x: c.end_date >= x["today"],
         "Plan period has ended. Upload an updated treatment plan."),
    Rule("dates_ordered", lambda c, x: c.start_date < c.end_date,
         "Plan start date must be before end date."),
    Rule("icd10_billable", lambda c, x: all(icd10_valid(d) for d in c.icd10_codes),
         "One or more ICD-10 codes are invalid or not billable."),
    Rule("cpt_matches_specialty", lambda c, x: set(c.cpt_codes) <= SPECIALTY_CPT[c.specialty],
         "Requested CPT codes do not match the specialty on the plan."),
    Rule("npi_valid", lambda c, x: npi_valid(c.provider.npi), "Provider NPI fails its checksum."),
    Rule("member_id_matches_payor", lambda c, x: c.patient.member_id.startswith(c.payor.payor_id),
         "Member ID format does not match the selected payor. Check the insurance card."),
]}


def _units_rule(limit: int) -> Rule:
    return Rule("units_within_payor_limit", lambda c, x: c.requested_units <= limit,
                f"Requested units exceed this payor's per-request limit of {limit}. Split the request.")


SCHOOL_RULE = Rule("school_schedule_attached", lambda c, x: c.school_schedule_attached,
                   "This payor requires the patient's school schedule for ABA hours on school days.")


class NLRule:
    """Plain-English rule answered by an LLM, strictly yes/no."""

    kind = "custom"

    def __init__(self, question: str, llm=None):
        self.name = "custom: " + question
        self.question = question
        self.llm = llm

    def run(self, case: Case, ctx: dict) -> RuleResult:
        text = ctx.get("documents_text", "")
        if self.llm is None or not text:
            return RuleResult(self.name, None, "LLM rules need ANTHROPIC_API_KEY and document text", "custom")
        r = self.llm.complete(
            f"Answer with exactly one word, YES or NO.\nQuestion: {self.question}\n\n"
            f"Document:\n<<<\n{text[:12000]}\n>>>", max_tokens=5)
        ans = r.text.strip().upper().rstrip(".")
        if ans not in ("YES", "NO"):  # forced cast: anything else is not a pass
            return RuleResult(self.name, None, f"non-boolean answer: {ans[:30]}", "custom")
        return RuleResult(self.name, ans == "YES", "" if ans == "YES" else self.question, "custom")


@dataclass
class ValidationReport:
    case_id: str
    results: list[RuleResult] = field(default_factory=list)

    @property
    def blocking(self) -> list[RuleResult]:
        return [r for r in self.results if r.passed is False]

    @property
    def needs_human(self) -> list[RuleResult]:
        return [r for r in self.results if r.passed is None]

    @property
    def ready(self) -> bool:
        return not self.blocking


def load_requirements(path: Path = REQ_PATH) -> dict:
    return yaml.safe_load(path.read_text())


def rules_for(case: Case, req: dict, llm=None) -> list:
    """Walk the configuration graph: defaults -> payor -> specialty -> gated rules."""
    rules: list = [DEFAULT_RULES[n] for n in req["defaults"]]
    spec = req["payors"].get(case.payor.payor_id, {}).get("specialties", {}).get(case.specialty, {})
    if "max_units_per_request" in spec:
        rules.append(_units_rule(spec["max_units_per_request"]))
    if spec.get("require_school_schedule"):
        rules.append(SCHOOL_RULE)
    for q in spec.get("custom_rules", []):
        rules.append(NLRule(q, llm))
    return rules


def validate_case(case: Case, today: date, req: dict | None = None, llm=None,
                  documents_text: str = "", include_custom: bool = True) -> ValidationReport:
    req = req or load_requirements()
    ctx = {"today": today, "documents_text": documents_text}
    rep = ValidationReport(case.case_id)
    for rule in rules_for(case, req, llm):
        if isinstance(rule, NLRule) and not include_custom:
            continue
        rep.results.append(rule.run(case, ctx))
    return rep
