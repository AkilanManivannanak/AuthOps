"""Trust replay: how much wrong data reaches payors with and without an evidence-gated QA ramp.

Three portals run for 60 days. On one of them a hidden fault starts on day 30 (a portal change
that makes the agent quietly submit a wrong field some share of the time). Only runs a person
reviews can reveal a wrong submission; anything not reviewed goes to the payor as is.

* No gate: the agent is trusted from day one and a fixed share of runs is spot-checked.
* Gate: `authops.ops.experiments.QARamp`, the ramp the agents use. Every run is reviewed until
  the 95% lower bound on clean runs clears its threshold; then review drops step by step to the
  spot-check floor, and a caught error pushes review back up.

Everything is precomputed over a grid of (fault size, spot-check rate, seed) so the page can
replay any combination instantly.
"""
from __future__ import annotations

import random

from authops.ops.experiments import QARamp

PORTALS = ["northwind", "summit", "keystone"]
FAULTY = "keystone"
DAYS, FAULT_DAY, RUNS_PER_DAY = 60, 30, 6
FAULTS = [0.0, 0.05, 0.1, 0.2, 0.3]
AUDITS = [0.5, 0.2, 0.1, 0.05]   # spot-check share once trusted: 1 in 2, 5, 10, 20
SEEDS = [1, 2, 3, 4, 5]


def simulate(fault: float, audit: float, seed: int) -> dict:
    out = {}
    for gated in (False, True):
        rng = random.Random(seed * 1000 + int(fault * 100) * 7 + int(audit * 100))
        ramp = QARamp(window=6, floor=audit, step=0.3, seed=seed)
        wrong, cum, caught = 0, [], 0
        share_log: dict[str, list[float]] = {p: [] for p in PORTALS}
        trusted_day = stopped_day = None
        for day in range(DAYS):
            for portal in PORTALS:
                for _ in range(RUNS_PER_DAY):
                    p_bad = 0.004 + (fault if portal == FAULTY and day >= FAULT_DAY else 0.0)
                    bad = rng.random() < p_bad
                    if gated:
                        reviewed = ramp.route_to_qa(portal)
                    else:
                        reviewed = rng.random() < audit
                    if bad and reviewed:
                        caught += 1
                    elif bad:
                        wrong += 1
                    if gated:  # the ramp learns only from what a person actually saw
                        ramp.record(portal, success=True, smooth=92 + rng.random() * 6, silent_error=bad and reviewed)
                if gated:
                    s = ramp.state.setdefault(portal, None)
                    share = s.qa_share if s else 1.0
                    share_log[portal].append(share)
                    if portal == FAULTY and trusted_day is None and share < 1.0:
                        trusted_day = day
                    if (portal == FAULTY and trusted_day is not None and stopped_day is None and day >= FAULT_DAY
                            and len(share_log[portal]) > 1 and share > share_log[portal][-2]):
                        stopped_day = day
            cum.append(wrong)
        key = "gate" if gated else "no_gate"
        out[key] = cum
        out[key + "_caught"] = caught
        if gated:
            lanes = []
            for p in PORTALS:
                st = ramp.state[p]
                clean = sum(1 for r in st.history if r["success"] and not r["silent_error"])
                raised = any(b > a for a, b in zip(share_log[p], share_log[p][1:]))
                status = ("stopped" if raised and st.qa_share > audit else
                          "trusted" if st.qa_share <= audit + 1e-9 else
                          "earning" if st.qa_share >= 1.0 else "ramping")
                lanes.append({"portal": p, "share": round(st.qa_share, 2), "runs": len(st.history), "clean": clean,
                              "status": status, "trace": [round(x, 2) for x in share_log[p]]})
            out["lanes"] = lanes
            out["trusted_day"], out["stopped_day"] = trusted_day, stopped_day
    return out


def build() -> dict:
    grid = {f"{f}|{a}|{s}": simulate(f, a, s) for f in FAULTS for a in AUDITS for s in SEEDS}
    return {"days": DAYS, "fault_day": FAULT_DAY, "faults": FAULTS, "audits": AUDITS, "seeds": SEEDS,
            "faulty": FAULTY, "runs_per_day": RUNS_PER_DAY, "grid": grid}
