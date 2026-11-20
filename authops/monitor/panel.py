"""Continuous coverage and authorization monitoring.

Silna sells "care readiness": verify benefits, keep the auth current, and keep watching the
patient's coverage between visits. Upstream issues (missing auths, outdated eligibility)
cause most claim denials, and specialty care makes them worse: ABA and PT patients visit
weekly for months, so an auth that runs out of units or a Medicaid plan that lapses at
redetermination silently turns every later visit into an unpaid claim.

This module simulates a patient panel for 26 weeks and compares three operating policies:

reactive   - the clinic learns about a problem when a claim is denied (about 3 weeks after
             the visit), then starts a reauthorization or fixes the coverage.
scheduled  - monthly eligibility checks and reauth started 14 days before the auth end date.
proactive  - weekly eligibility checks plus a unit burn-down forecast: the reauth starts when
             the projected exhaustion date is closer than the payor's 90th percentile
             turnaround plus a safety buffer; coverage changes trigger a same-week fix.

Every number is from the simulation; nothing here is a claim about Silna's customers.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

SPECIALTY = {  # visits per week (mean), billed amount per visit, auth length weeks, units per visit
    "aba": dict(visits=4.0, rate=420.0, auth_weeks=26, units_per_visit=5),
    "physical_therapy": dict(visits=2.0, rate=140.0, auth_weeks=8, units_per_visit=1),
    "behavioral_health": dict(visits=1.0, rate=160.0, auth_weeks=12, units_per_visit=1),
}
PAYOR_TURNAROUND = {"commercial": (5, 12), "medicaid_mco": (7, 16)}  # business days (p50, p90)


@dataclass
class Patient:
    pid: str
    specialty: str
    plan_type: str
    auth_start: int          # day index
    auth_end: int
    units_approved: int
    units_used: int = 0
    covered_until: int = 10_000   # day coverage terminates (redetermination lapse, job change)
    switch_day: int | None = None  # day the patient moved to a different payor/member ID
    visits_per_week: float = 2.0
    events: list = field(default_factory=list)


def make_panel(n: int = 200, seed: int = 5, weeks: int = 26) -> list[Patient]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        spec = rng.choices(list(SPECIALTY), weights=[0.45, 0.35, 0.20])[0]
        s = SPECIALTY[spec]
        plan = "medicaid_mco" if rng.random() < 0.45 else "commercial"
        start = -rng.randint(0, s["auth_weeks"] * 7 - 7)
        length = s["auth_weeks"] * 7
        vpw = max(0.5, rng.gauss(s["visits"], s["visits"] * 0.25))
        planned_units = int(s["visits"] * s["auth_weeks"] * s["units_per_visit"])
        # some auths are approved for fewer units than the visit rate will burn (partial approvals)
        approved = int(planned_units * (rng.uniform(0.6, 0.85) if rng.random() < 0.3 else rng.uniform(0.95, 1.15)))
        p = Patient(f"P{i:03d}", spec, plan, start, start + length, approved, visits_per_week=vpw)
        p.units_used = int(max(0, -start) / 7 * vpw * s["units_per_visit"])
        horizon = weeks * 7
        if plan == "medicaid_mco" and rng.random() < 0.12:     # redetermination lapse
            p.covered_until = rng.randint(14, horizon - 14)
        elif rng.random() < 0.05:                               # commercial coverage ends
            p.covered_until = rng.randint(14, horizon - 14)
        if rng.random() < 0.06:                                 # payor switch, new member ID
            p.switch_day = rng.randint(14, horizon - 14)
        out.append(p)
    return out


@dataclass
class PolicyResult:
    policy: str
    visits: int = 0
    denied_visits: int = 0
    denied_dollars: float = 0.0
    days_without_valid_auth: int = 0
    reauths: int = 0
    eligibility_checks: int = 0
    alerts: int = 0
    useful_alerts: int = 0
    by_cause: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["denied_dollars"] = round(self.denied_dollars)
        d["alert_precision"] = round(self.useful_alerts / self.alerts, 3) if self.alerts else None
        return d


def simulate(panel: list[Patient], policy: str, weeks: int = 26, seed: int = 9, buffer_days: int = 7) -> PolicyResult:
    rng = random.Random(seed)
    res = PolicyResult(policy)
    for p0 in panel:
        p = Patient(**{k: getattr(p0, k) for k in p0.__dataclass_fields__ if k != "events"})
        s = SPECIALTY[p.specialty]
        p50, p90 = PAYOR_TURNAROUND[p.plan_type]
        auth_ok_until, units_left = p.auth_end, p.units_approved - p.units_used
        reauth_pending_until: int | None = None
        coverage_fixed_on: int | None = None
        switch_fixed_on: int | None = None
        known_problem_day: dict[str, int] = {}
        for day in range(weeks * 7):
            # payor decision on a pending reauth lands: new auth window and units
            if reauth_pending_until is not None and day >= reauth_pending_until:
                auth_ok_until = day + s["auth_weeks"] * 7
                units_left = int(s["visits"] * s["auth_weeks"] * s["units_per_visit"] * 1.0)
                reauth_pending_until = None
            # monitoring
            check_elig = (policy == "proactive" and day % 7 == 0) or (policy == "scheduled" and day % 30 == 0)
            if check_elig:
                res.eligibility_checks += 1
                if day >= p.covered_until and coverage_fixed_on is None:
                    res.alerts += 1
                    res.useful_alerts += 1
                    coverage_fixed_on = day + rng.randint(5, 15)     # new coverage enrolled / Medicaid restored
                if p.switch_day is not None and day >= p.switch_day and switch_fixed_on is None:
                    res.alerts += 1
                    res.useful_alerts += 1
                    switch_fixed_on = day + p90 + 2                  # new payor needs its own auth
            if reauth_pending_until is None and policy != "reactive":
                days_left = auth_ok_until - day
                weekly_burn = p.visits_per_week * s["units_per_visit"]
                if policy == "proactive":
                    weeks_to_empty = units_left / weekly_burn if weekly_burn else 99
                    trigger = min(days_left, weeks_to_empty * 7) <= p90 * 7 / 5 + buffer_days
                    if trigger and day % 7 == 0:
                        res.alerts += 1
                        useful = min(days_left, weeks_to_empty * 7) <= weeks * 7 - day
                        res.useful_alerts += int(useful)
                        res.reauths += 1
                        reauth_pending_until = day + int(rng.uniform(p50, p90) * 7 / 5)
                else:
                    if days_left == 14:
                        res.reauths += 1
                        reauth_pending_until = day + int(rng.uniform(p50, p90) * 7 / 5)
            if (day >= p.covered_until and (coverage_fixed_on is None or day < coverage_fixed_on)) \
                    or day > auth_ok_until or units_left < s["units_per_visit"]:
                res.days_without_valid_auth += 1
            # visit?
            if rng.random() < p.visits_per_week / 7:
                res.visits += 1
                cause = None
                if day >= p.covered_until and (coverage_fixed_on is None or day < coverage_fixed_on):
                    cause = "coverage_lapsed"
                elif p.switch_day is not None and day >= p.switch_day and (switch_fixed_on is None or day < switch_fixed_on):
                    cause = "payor_changed"
                elif day > auth_ok_until:
                    cause = "auth_expired"
                elif units_left < s["units_per_visit"]:
                    cause = "units_exhausted"
                if cause:
                    res.denied_visits += 1
                    res.denied_dollars += s["rate"]
                    res.by_cause[cause] = res.by_cause.get(cause, 0) + 1
                    # every policy eventually learns from the denial (~21 days later) and acts
                    if cause not in known_problem_day:
                        known_problem_day[cause] = day + 21
                else:
                    units_left -= s["units_per_visit"]
            # reactive fixes once the denial is discovered
            for cause, when in list(known_problem_day.items()):
                if day >= when:
                    known_problem_day.pop(cause)
                    if cause in ("auth_expired", "units_exhausted") and reauth_pending_until is None:
                        res.reauths += 1
                        reauth_pending_until = day + int(rng.uniform(p50, p90) * 7 / 5)
                    elif cause == "coverage_lapsed" and coverage_fixed_on is None:
                        coverage_fixed_on = day + rng.randint(5, 15)
                    elif cause == "payor_changed" and switch_fixed_on is None:
                        switch_fixed_on = day + p90 + 2
    return res


def compare(n: int = 200, seed: int = 5, weeks: int = 26) -> dict:
    panel = make_panel(n, seed, weeks)
    out = {pol: simulate(panel, pol, weeks).as_dict() for pol in ("reactive", "scheduled", "proactive")}
    base = out["reactive"]["denied_dollars"] or 1
    for pol in out:
        out[pol]["denied_dollars_vs_reactive"] = round(1 - out[pol]["denied_dollars"] / base, 3)
    out["panel"] = {"patients": n, "weeks": weeks,
                    "medicaid_share": round(sum(p.plan_type == "medicaid_mco" for p in panel) / n, 2),
                    "partial_approvals": sum(p.units_approved < SPECIALTY[p.specialty]["visits"] *
                                             SPECIALTY[p.specialty]["auth_weeks"] *
                                             SPECIALTY[p.specialty]["units_per_visit"] * 0.9 for p in panel),
                    "coverage_lapses": sum(p.covered_until < weeks * 7 for p in panel),
                    "payor_switches": sum(p.switch_day is not None for p in panel)}
    return out


def forecast(units_left: int, weekly_units: float, days_left: int, p90_business_days: int,
             buffer_days: int = 7) -> dict:
    """Burn-down forecast for one auth, used by the app and the API."""
    weeks_to_empty = units_left / weekly_units if weekly_units > 0 else float("inf")
    runway = min(days_left, weeks_to_empty * 7)
    lead = p90_business_days * 7 / 5 + buffer_days
    return {"days_until_units_run_out": None if weeks_to_empty == float("inf") else round(weeks_to_empty * 7),
            "days_until_auth_ends": days_left, "runway_days": round(runway),
            "reauth_lead_days": round(lead), "start_reauth_now": runway <= lead,
            "binding_limit": "units" if weeks_to_empty * 7 < days_left else "end date"}
