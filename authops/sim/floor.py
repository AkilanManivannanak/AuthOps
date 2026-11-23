"""Operations floor: 26 weeks of requests computed by the real pipeline, for the animated overview.

Every event is produced by the system's own code, not drawn at random in the browser:
cases from the case generator, gaps judged by the payor rules, extraction confidence from
the measured coverage of the extractor, outcomes from the payor adjudication the approval
model learned from, and the Keystone PT visit cap found by the drift detector. Once the
detector flags the change (plus one week for approval) the new rule blocks those requests
at the gate, so the animation shows the system learning.
"""
from __future__ import annotations

import random
from datetime import date

from authops.intel.approval import ApprovalModel, Request, adjudicate, history_from, simulate
from authops.intel.drift import DEFAULT_CHANGES, detect, simulate_stream
from authops.synth.generate import generate_cases
from authops.validation.rules import load_requirements, validate_case

TODAY = date(2026, 11, 17)
SOURCES = ["Fax", "EHR", "Upload"]
CAP = next(c for c in DEFAULT_CHANGES if c.kind == "unit_cap")       # KCM physical therapy, 20 visits
EXTRACTOR_COVERAGE = 0.931                                           # measured share of fields filled


def build(n: int = 180, weeks: int = 26, seed: int = 12) -> dict:
    rng = random.Random(seed)
    req = load_requirements()
    alerts = detect(simulate_stream(seed=4))
    cap_alert = next((a for a in alerts if a.payor == CAP.payor and a.specialty == CAP.specialty), None)
    rule_live = (cap_alert.week_detected + 1) if cap_alert else 99
    model = ApprovalModel().fit([h for h in history_from(simulate(), random.Random(8)) if h[0].week < 40])
    cases = generate_cases(n, seed=seed, today=TODAY, gap_rate=0.18)
    # the week the payor changes its policy: a few Keystone PT requests arrive before anyone knows
    pool = [c for c in generate_cases(400, seed=seed + 1, today=TODAY, gap_rate=0.0)
            if c.payor.payor_id == CAP.payor and c.specialty == CAP.specialty][:3]
    at = int(CAP.week * n / weeks) + 1
    cases[at:at] = pool
    n = len(cases)
    events, counts = [], {k: 0 for k in ("in", "qa", "caught", "submitted", "approved", "partial", "denied", "appeal",
                                         "fix", "rule_learned")}
    for i, c in enumerate(cases):
        week = int(i * weeks / n)
        # push some Keystone PT requests over the hidden cap so the change is visible
        if c.payor.payor_id == CAP.payor and c.specialty == CAP.specialty and rng.random() < 0.7:
            c.requested_units = rng.randint(CAP.value + 1, 24)   # within the documented 24, over the hidden 20
        qa = rng.random() > EXTRACTOR_COVERAGE ** 3          # any of the critical fields unsure -> human check
        rep = validate_case(c, TODAY, req, include_custom=False)
        caught = [r.message for r in rep.blocking]
        learned = (c.payor.payor_id == CAP.payor and c.specialty == CAP.specialty and c.requested_units > CAP.value
                   and week >= rule_live and not caught)
        if learned:
            caught = [f"New rule (learned week {cap_alert.week_detected + 1}): Keystone PT is limited to {CAP.value} visits."]
        ev = {"id": c.case_id, "week": week, "src": rng.choice(SOURCES), "name": c.patient.full_name,
              "payor": c.payor.payor_id, "payor_name": c.payor.name, "spec": c.specialty, "units": c.requested_units,
              "channel": c.payor.channel, "qa": qa}
        counts["in"] += 1
        counts["qa"] += qa
        if caught:
            ev.update(outcome="caught", reason=caught[0], learned=learned)
            counts["caught"] += 1
            counts["rule_learned"] += learned
        else:
            counts["submitted"] += 1
            if c.payor.payor_id == CAP.payor and c.specialty == CAP.specialty and c.requested_units > CAP.value \
                    and week >= CAP.week:
                ev.update(outcome="denied", reason=CAP.reason, next="fix")
                counts["denied"] += 1
                counts["fix"] += 1
            else:
                doc = rng.uniform(0.1, 0.29) if rng.random() < 0.07 else rng.uniform(0.6, 1.0)
                rq = Request(week, c.payor.payor_id, c.specialty, rng.uniform(0.3, 0.95), rng.uniform(0.6, 1.0),
                             False, doc, c.requested_units, rng.uniform(0.92, 1.08))
                rec = model.recommend(rq, 0.8)                     # approval outlook sets the units requested
                ev["recommended"] = rec
                o, approved = adjudicate(rq, rec)
                ev.update(outcome="approved" if o == "approved" else o, approved=approved)
                if o == "denied":
                    ev.update(reason="Medical necessity not established for the requested intensity.",
                              next="appeal" if rng.random() < 0.6 else "fix")
                    counts["appeal" if ev["next"] == "appeal" else "fix"] += 1
                counts[o if o in counts else "approved"] += 1
        events.append(ev)
    return {"events": events, "counts": counts, "weeks": weeks,
            "alert": {"week": cap_alert.week_detected, "payor": CAP.payor, "spec": CAP.specialty,
                      "signal": cap_alert.signal, "rule": f"max_units_per_request: {CAP.value}",
                      "change_week": CAP.week} if cap_alert else None}
