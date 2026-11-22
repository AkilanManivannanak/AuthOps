"""Payor policy drift: find unannounced rule changes in the decision stream, and propose the rule.

Payors change requirements through bulletins, provider-manual edits and sometimes nothing at all.
Until the requirements database catches up, every affected request is submitted, denied and
reworked. Requirements teams usually learn about a change from a bulletin or from a monthly
denial review.

This module watches every payor decision as it arrives and, per payor x specialty:

  1. one-sided CUSUM on each denial reason and on the partial-approval rate (statistical
     process control: alarms on a sustained shift, not on one bad day);
  2. a new-reason trigger (a denial reason never seen before for that pair);
  3. cap inference: partial approvals that cluster on one approved-units value imply a soft cap;
  4. a turnaround monitor: a shift in days-to-decision, which changes how early reauths must start.

Each alarm becomes a proposed edit to configs/payor_requirements.yaml with its evidence (rates
before and after, the estimated change week, example cases) for a person to approve.

The stream is synthetic with known change weeks, so detection delay, false alarms and the
correctness of the proposed rule are all measurable. Decoys that are not policy changes (a volume
surge, noise) are included to measure false alarms.
"""
from __future__ import annotations

import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

PAIRS = [("NWH", "aba"), ("NWH", "physical_therapy"), ("NWH", "behavioral_health"),
         ("KCM", "aba"), ("KCM", "physical_therapy"), ("KCM", "behavioral_health"),
         ("SFB", "aba"), ("SFB", "physical_therapy"), ("SFB", "behavioral_health"),
         ("HBL", "physical_therapy")]
UNITS = {"aba": (80, 400), "physical_therapy": (8, 30), "behavioral_health": (6, 24)}
COVERED_BY = {  # denial reasons that an existing validation rule already checks before submission
    "Treatment plan is not signed by the rendering provider.": "signature_present",
    "Diagnosis code is invalid or not billable.": "icd10_billable",
    "Submitted treatment plan dates have expired.": "plan_not_expired",
}
BASE_DENIAL = {  # background denial reasons present all along (documentation gaps etc.)
    "Treatment plan is not signed by the rendering provider.": 0.03,
    "Diagnosis code is invalid or not billable.": 0.025,
    "Submitted treatment plan dates have expired.": 0.02,
}


@dataclass
class Change:
    kind: str           # unit_cap | new_requirement | soft_cap | turnaround
    payor: str
    specialty: str
    week: int
    value: float | str
    reason: str = ""


DEFAULT_CHANGES = [
    Change("unit_cap", "KCM", "physical_therapy", 8, 20,
           "Physical therapy is limited to 20 visits per authorization period."),
    Change("new_requirement", "NWH", "aba", 12, "assessment within 6 months",
           "Standardized assessment must be dated within 6 months of the request."),
    Change("soft_cap", "SFB", "behavioral_health", 15, 16),
    Change("turnaround", "HBL", "physical_therapy", 10, 9),
]
DECOYS = [("volume_surge", "NWH", "physical_therapy", 18)]


@dataclass
class Decision:
    week: int
    case_id: str
    payor: str
    specialty: str
    requested: int
    outcome: str          # approved | partial | denied
    approved: int
    reason: str | None
    days_to_decision: int


def simulate_stream(weeks: int = 26, per_pair_week: int = 14, seed: int = 3,
                    changes: list[Change] | None = None, decoys=DECOYS) -> list[Decision]:
    rng = random.Random(seed)
    changes = DEFAULT_CHANGES if changes is None else changes
    out, n = [], 0
    for w in range(weeks):
        for payor, spc in PAIRS:
            vol = per_pair_week
            if any(d[0] == "volume_surge" and d[1] == payor and d[2] == spc and w >= d[3] for d in decoys):
                vol *= 2
            vol = max(1, int(rng.gauss(vol, vol * 0.2)))
            for _ in range(vol):
                n += 1
                lo, hi = UNITS[spc]
                req = rng.randint(lo, hi)
                days = max(1, int(rng.gauss(4, 1.2)))
                act = [c for c in changes if c.payor == payor and c.specialty == spc and w >= c.week]
                outcome, approved, reason = "approved", req, None
                for r, p in BASE_DENIAL.items():
                    if rng.random() < p:
                        outcome, approved, reason = "denied", 0, r
                        break
                if outcome == "approved":
                    for c in act:
                        if c.kind == "unit_cap" and req > c.value:
                            outcome, approved, reason = "denied", 0, c.reason
                        elif c.kind == "new_requirement" and rng.random() < 0.35:
                            outcome, approved, reason = "denied", 0, c.reason
                        elif c.kind == "soft_cap" and req > c.value:
                            outcome, approved = "partial", int(c.value)
                        elif c.kind == "turnaround":
                            days = max(1, int(rng.gauss(c.value, 2)))
                if outcome == "approved" and rng.random() < 0.08:   # ordinary partials, scattered values
                    outcome, approved = "partial", max(1, int(req * rng.choice([0.5, 0.6, 0.75])))
                out.append(Decision(w, f"D{n:06d}", payor, spc, req, outcome, approved, reason, days))
    return out


# ------------------------------------------------------------------ detection

@dataclass
class Alert:
    kind: str
    payor: str
    specialty: str
    week_detected: int
    week_estimated: int
    signal: str
    rate_before: float
    rate_after: float
    n_after: int
    proposal: dict
    examples: list[str] = field(default_factory=list)
    evidence: str = ""


def _cusum_bernoulli(xs: list[tuple[int, int]], p0: float, p1: float, h: float) -> tuple[int | None, int]:
    """xs: per-week (events, trials). Returns (alarm week index, estimated start index)."""
    p0, p1 = min(max(p0, 1e-3), 0.9), min(max(p1, p0 + 1e-3), 0.99)
    a, b = math.log(p1 / p0), math.log((1 - p1) / (1 - p0))
    s, start = 0.0, 0
    for i, (k, n) in enumerate(xs):
        s_prev = s
        s = max(0.0, s + k * a + (n - k) * b)
        if s_prev == 0.0 and s > 0:
            start = i
        if s > h:
            return i, start
    return None, start


def _cusum_mean(xs: list[float], mu0: float, sd: float, shift: float, h: float) -> tuple[int | None, int]:
    s, start = 0.0, 0
    for i, x in enumerate(xs):
        s_prev = s
        s = max(0.0, s + (x - mu0 - shift / 2) / max(sd, 1e-6))
        if s_prev == 0.0 and s > 0:
            start = i
        if s > h:
            return i, start
    return None, start


def detect(stream: list[Decision], h: float = 6.0, warmup: int = 6, min_new_reason: int = 3, min_events: int = 5,
           known_reasons: set[str] | None = None) -> list[Alert]:
    by_pair: dict = defaultdict(list)
    for d in stream:
        by_pair[(d.payor, d.specialty)].append(d)
    weeks = max(d.week for d in stream) + 1
    alerts: list[Alert] = []
    known = set(known_reasons or BASE_DENIAL)
    # pooled warm-up rate per reason across all payors: a stable prior for small per-pair counts
    warm = [d for d in stream if d.week < warmup]
    pooled = {r: (sum(d.reason == r for d in warm) + 0.5) / (len(warm) + 1) for r in {d.reason for d in stream if d.reason}}
    prior_n = 150
    for (payor, spc), ds in by_pair.items():
        wk = [[d for d in ds if d.week == w] for w in range(weeks)]
        base = [d for w in wk[:warmup] for d in w]
        if not base:
            continue
        # 1 + 2: denial reasons
        reasons = Counter(d.reason for d in ds if d.reason)
        for r in reasons:
            series = [(sum(d.reason == r for d in w), len(w)) for w in wk]
            k0, n0 = sum(k for k, _ in series[:warmup]), sum(n for _, n in series[:warmup])
            p0 = (k0 + prior_n * pooled.get(r, 0.01)) / (n0 + prior_n)
            alarm, start = _cusum_bernoulli(series[warmup:], p0, max(3 * p0, p0 + 0.08), h)
            if alarm is not None and sum(k for k, _ in series[warmup + start:warmup + alarm + 1]) < min_events:
                alarm = None
            new_reason = r not in known
            first_seen = next((i for i, (k, _) in enumerate(series) if k), None)
            if new_reason and first_seen is not None:
                cum = 0
                for i, (k, _) in enumerate(series[first_seen:], first_seen):
                    cum += k
                    if cum >= min_new_reason:
                        alarm_new = i
                        break
                else:
                    alarm_new = None
            else:
                alarm_new = None
            cands = [x for x in ((alarm + warmup) if alarm is not None else None, alarm_new) if x is not None]
            if not cands:
                continue
            wd = min(cands)
            est = first_seen if (alarm_new is not None and wd == alarm_new) else start + warmup
            before = [s for s in series[:est]]
            after = [s for s in series[est:wd + 1]]
            rb = sum(k for k, _ in before) / max(1, sum(n for _, n in before))
            ra = sum(k for k, _ in after) / max(1, sum(n for _, n in after))
            ex = [d.case_id for w in wk[est:wd + 1] for d in w if d.reason == r][:3]
            alerts.append(Alert("denial_reason", payor, spc, wd, est, r, round(rb, 3), round(ra, 3),
                                sum(n for _, n in after), propose_from_reason(payor, spc, r, ds), ex,
                                "new denial reason" if alarm_new is not None and wd == alarm_new else "rate shift (CUSUM)"))
        # 3: partial approvals clustering on one value
        series = [(sum(d.outcome == "partial" for d in w), len(w)) for w in wk]
        p0 = (sum(k for k, _ in series[:warmup]) + 0.5) / (sum(n for _, n in series[:warmup]) + 1)
        alarm, start = _cusum_bernoulli(series[warmup:], p0, max(2.0 * p0, p0 + 0.12), h)
        if alarm is not None:
            wd, est = alarm + warmup, start + warmup
            parts = [d for w in wk[est:wd + 1] for d in w if d.outcome == "partial"]
            vals = Counter(d.approved for d in parts)
            k, c = vals.most_common(1)[0] if vals else (None, 0)
            if k is not None and c >= max(4, 0.4 * len(parts)):
                rb = sum(x for x, _ in series[:est]) / max(1, sum(n for _, n in series[:est]))
                ra = sum(x for x, _ in series[est:wd + 1]) / max(1, sum(n for _, n in series[est:wd + 1]))
                alerts.append(Alert("soft_cap", payor, spc, wd, est, f"partial approvals at {k} units", round(rb, 3),
                                    round(ra, 3), sum(n for _, n in series[est:wd + 1]),
                                    {"specialties": {spc: {"recommend_max_units": int(k)}}, "payor": payor,
                                     "note": f"{c} of {len(parts)} partial approvals were cut to exactly {k} units"},
                                    [d.case_id for d in parts[:3]], "partial-approval cluster"))
        # 4: turnaround
        means = [sum(d.days_to_decision for d in w) / len(w) if w else 0 for w in wk]
        b = [d.days_to_decision for d in base]
        mu0 = sum(b) / len(b)
        sd = (sum((x - mu0) ** 2 for x in b) / len(b)) ** 0.5 / max(1, (len(base) / warmup)) ** 0.5
        alarm, start = _cusum_mean(means[warmup:], mu0, sd, max(2.0, 4 * sd), h)
        if alarm is not None:
            wd, est = alarm + warmup, start + warmup
            after = [d.days_to_decision for w in wk[est:wd + 1] for d in w]
            new_mu = sum(after) / max(1, len(after))
            p90 = sorted(after)[int(0.9 * (len(after) - 1))] if after else None
            alerts.append(Alert("turnaround", payor, spc, wd, est, "days to decision", round(mu0, 1), round(new_mu, 1),
                                len(after), {"payor": payor, "specialties": {spc: {"turnaround_p90_days": p90}},
                                             "note": "start reauthorizations earlier for this payor"},
                                [], "turnaround shift (CUSUM)"))
    return sorted(alerts, key=lambda a: a.week_detected)


def severity(a: Alert) -> int:
    """New reasons and caps first, turnaround next, rises in already-covered reasons last."""
    if a.kind == "denial_reason" and a.signal in COVERED_BY:
        return 1
    return {"denial_reason": 4, "soft_cap": 3, "turnaround": 2}.get(a.kind, 1)


def propose_from_reason(payor: str, spc: str, reason: str, ds: list[Decision]) -> dict:
    if reason in COVERED_BY:
        return {"payor": payor, "action": "investigate", "specialties": {spc: {"check_rule": COVERED_BY[reason]}},
                "note": f"No new rule: '{COVERED_BY[reason]}' already checks this before submission. A rise means "
                        "requests are reaching the payor without it (bypassed validation, a document type it does "
                        "not read, or a stricter payor reading). Pull the example decisions and compare."}
    m = re.search(r"limited to (\d+) (visits|units|hours)", reason, re.I)
    if m:
        cap = int(m.group(1))
        denied = [d.requested for d in ds if d.reason == reason]
        ok = [d.requested for d in ds if d.outcome == "approved"]
        consistent = all(x > cap for x in denied)
        return {"payor": payor, "specialties": {spc: {"max_units_per_request": cap}},
                "note": f"all {len(denied)} denials requested more than {cap}" if consistent else
                f"cap {cap} from the reason text; {sum(x <= cap for x in denied)} denials at or under it need review",
                "approved_max_after": max(ok) if ok else None}
    return {"payor": payor, "specialties": {spc: {"custom_rules": [f"Does the request meet this payor requirement: '{reason}'?"]}},
            "note": "new documentation requirement; phrase as a yes/no rule and backtest before enabling"}


# ------------------------------------------------------------------ evaluation

def match(alerts: list[Alert], changes: list[Change]) -> dict:
    """Pair each true change with its first alert on the same payor x specialty."""
    rows, used = [], set()
    for c in changes:
        hits = [a for a in alerts if a.payor == c.payor and a.specialty == c.specialty and a.week_detected >= c.week
                and a.signal not in BASE_DENIAL]
        a = hits[0] if hits else None
        if a:
            used.add(id(a))
        correct = None
        if a and c.kind == "unit_cap":
            correct = a.proposal.get("specialties", {}).get(c.specialty, {}).get("max_units_per_request") == c.value
        if a and c.kind == "soft_cap":
            correct = a.proposal.get("specialties", {}).get(c.specialty, {}).get("recommend_max_units") == c.value
        if a and c.kind == "new_requirement":
            correct = bool(a.proposal.get("specialties", {}).get(c.specialty, {}).get("custom_rules"))
        if a and c.kind == "turnaround":
            correct = a.kind == "turnaround"
        rows.append({"change": c.kind, "payor": c.payor, "specialty": c.specialty, "true_week": c.week,
                     "detected_week": a.week_detected if a else None,
                     "delay_weeks": (a.week_detected - c.week) if a else None, "proposal_correct": correct})
    false_alarms = [a for a in alerts if id(a) not in used]
    return {"changes": rows, "false_alarms": len(false_alarms),
            "false_alarm_detail": [f"{a.payor}/{a.specialty}: {a.signal} (week {a.week_detected})" for a in false_alarms]}


def denials_avoided(stream: list[Decision], changes: list[Change], detected_week: dict, manual_delay_weeks: int = 6,
                    approval_lag_weeks: int = 1) -> dict:
    """Denials caused by each change that happen after the rule could be live, vs a manual discovery baseline."""
    out = {}
    for c in changes:
        if c.kind not in ("unit_cap", "new_requirement"):
            continue
        hits = [d for d in stream if d.payor == c.payor and d.specialty == c.specialty and d.reason == c.reason]
        dw = detected_week.get((c.payor, c.specialty))
        auto_live = (dw + approval_lag_weeks) if dw is not None else 10 ** 6
        manual_live = c.week + manual_delay_weeks
        out[f"{c.payor}/{c.specialty}"] = {
            "denials_total": len(hits),
            "denials_before_auto_rule": sum(d.week < auto_live for d in hits),
            "denials_before_manual_rule": sum(d.week < manual_live for d in hits),
        }
    return out


def evaluate(seeds: int = 20, h: float = 6.0) -> dict:
    delays, correct, fa, avoided_auto, avoided_manual = defaultdict(list), defaultdict(list), [], 0, 0
    for s in range(seeds):
        st = simulate_stream(seed=s)
        al = detect(st, h=h)
        m = match(al, DEFAULT_CHANGES)
        fa.append(m["false_alarms"])
        dw = {}
        for r in m["changes"]:
            if r["delay_weeks"] is not None:
                delays[r["change"]].append(r["delay_weeks"])
                dw[(r["payor"], r["specialty"])] = r["detected_week"]
            correct[r["change"]].append(bool(r["proposal_correct"]))
        for v in denials_avoided(st, DEFAULT_CHANGES, dw).values():
            avoided_auto += v["denials_before_auto_rule"]
            avoided_manual += v["denials_before_manual_rule"]
    return {"seeds": seeds, "threshold_h": h,
            "detection_rate": {k: round(len(delays[k]) / seeds, 3) for k in correct},
            "median_delay_weeks": {k: sorted(v)[len(v) // 2] if v else None for k, v in delays.items()},
            "proposal_correct": {k: round(sum(v) / len(v), 3) for k, v in correct.items()},
            "false_alarms_per_26_weeks": round(sum(fa) / seeds, 2),
            "denials_before_rule": {"automatic": avoided_auto, "manual_6_weeks": avoided_manual}}
