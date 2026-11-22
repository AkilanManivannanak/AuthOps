"""Approval outlook: how likely is a request to be approved in full, and how many units to ask for.

A partial approval is a quiet failure: the request goes through, the payor approves fewer units
than asked, and the clinic learns it weeks later. Then it either resubmits for the remainder or
the patient's schedule is cut mid-authorization. Most partial approvals are predictable from the
payor, the specialty, the documented severity and how much of the last authorization was used.

The decision history only shows the payor's ceiling when a request was cut (partial approval);
a full approval only says the ceiling was at least what was asked. Instead of regressing a
censored number, the model learns P(full approval | request features, units requested) directly,
then scans unit counts to find the largest request that clears a target probability.

Evaluation is a time split: train on the first 40 weeks, test on the last 12, against the true
adjudication process of the simulator, so every policy (ask for the clinical need, take a fixed
haircut, follow the model) is scored on the same requests.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import brier_score_loss, roc_auc_score

PAYORS = ["NWH", "KCM", "SFB", "HBL", "PRV"]
SPECS = ["aba", "physical_therapy", "behavioral_health"]
# hidden adjudication ceilings by payor x specialty (units per request at maximum severity)
CEILING = {
    ("NWH", "aba"): 420, ("NWH", "physical_therapy"): 30, ("NWH", "behavioral_health"): 22,
    ("KCM", "aba"): 360, ("KCM", "physical_therapy"): 20, ("KCM", "behavioral_health"): 18,
    ("SFB", "aba"): 400, ("SFB", "physical_therapy"): 28, ("SFB", "behavioral_health"): 16,
    ("HBL", "aba"): 440, ("HBL", "physical_therapy"): 32, ("HBL", "behavioral_health"): 24,
    ("PRV", "aba"): 380, ("PRV", "physical_therapy"): 26, ("PRV", "behavioral_health"): 20,
}


@dataclass
class Request:
    week: int
    payor: str
    specialty: str
    severity: float        # standardized assessment, 0 (mild) to 1 (severe)
    utilization: float     # share of the previous authorization actually used (0 for first auth)
    first_auth: bool
    doc_score: float       # documentation completeness 0-1
    need: int              # units the clinician would request by default
    noise: float           # reviewer variation, part of the true process only


def approvable(r: Request) -> int:
    """True payor ceiling for this request (hidden from the model)."""
    cap = CEILING[(r.payor, r.specialty)]
    util = 1.0 if r.first_auth else min(1.0, 0.55 + 0.5 * r.utilization)
    return max(1, int(cap * (0.45 + 0.55 * r.severity) * util * r.noise))


def adjudicate(r: Request, requested: int) -> tuple[str, int]:
    a = approvable(r)
    if r.doc_score < 0.3:
        return "denied", 0
    if requested <= a:
        return "approved", requested
    return "partial", a


def simulate(n_weeks: int = 52, per_week: int = 120, seed: int = 7) -> list[Request]:
    rng = random.Random(seed)
    out = []
    for w in range(n_weeks):
        for _ in range(per_week):
            p, s = rng.choice(PAYORS), rng.choice(SPECS)
            first = rng.random() < 0.3
            r = Request(w, p, s, min(1, max(0, rng.betavariate(2.2, 2.0))), 0.0 if first else rng.uniform(0.3, 1.15),
                        first, min(1, max(0, rng.gauss(0.8, 0.18))), 0, rng.uniform(0.9, 1.1))
            # clinicians ask for what the patient needs, which often exceeds what the payor will fund
            r.need = max(2, int(approvable(r) / r.noise * rng.uniform(0.8, 1.45)))
            out.append(r)
    return out


def features(r: Request, requested: int) -> list[float]:
    cap_hint = {"aba": 400.0, "physical_therapy": 26.0, "behavioral_health": 20.0}[r.specialty]
    return ([float(r.payor == p) for p in PAYORS] + [float(r.specialty == s) for s in SPECS] +
            [r.severity, r.utilization, float(r.first_auth), r.doc_score, requested / cap_hint, math.log1p(requested)])


class ApprovalModel:
    def __init__(self, seed: int = 0):
        self.clf = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06, random_state=seed)
        self.cut = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.06, random_state=seed)

    def fit(self, history: list[tuple[Request, int, str, int]]) -> "ApprovalModel":
        docs_ok = [(r, q, o, a) for r, q, o, a in history if o != "denied"]
        X = np.array([features(r, q) for r, q, _, _ in docs_ok])
        y = np.array([o == "approved" for _, _, o, _ in docs_ok])
        self.clf.fit(X, y)
        parts = [(r, q, a) for r, q, o, a in docs_ok if o == "partial"]
        self.cut.fit(np.array([features(r, q) for r, q, _ in parts]), np.array([a / q for _, q, a in parts]))
        return self

    def p_full(self, r: Request, requested: int) -> float:
        return float(self.clf.predict_proba(np.array([features(r, requested)]))[0, 1])

    def outlook(self, r: Request, requested: int) -> dict:
        p = self.p_full(r, requested)
        frac = float(np.clip(self.cut.predict(np.array([features(r, requested)]))[0], 0.05, 1.0))
        return {"p_full": round(p, 3), "expected_units": round(p * requested + (1 - p) * frac * requested, 1),
                "if_cut_units": int(frac * requested)}

    def recommend(self, r: Request, target: float = 0.8) -> int:
        """Largest request up to the clinical need whose P(full approval) clears the target."""
        qs = list(range(r.need, 0, -max(1, r.need // 60)))
        ps = self.clf.predict_proba(np.array([features(r, q) for q in qs]))[:, 1]
        ok = [q for q, p in zip(qs, ps) if p >= target]
        return ok[0] if ok else max(1, int(r.need * 0.5))

    def curve(self, r: Request, points: int = 30) -> list[dict]:
        hi = max(2, int(r.need * 1.3))
        qs = sorted({max(1, int(hi * k / points)) for k in range(1, points + 1)})
        X = np.array([features(r, q) for q in qs])
        ps = self.clf.predict_proba(X)[:, 1]
        return [{"units": q, "p_full": float(p)} for q, p in zip(qs, ps)]


def history_from(reqs: list[Request], policy_rng: random.Random) -> list[tuple[Request, int, str, int]]:
    """What the clinics actually requested in the past (their default: the clinical need, sometimes trimmed)."""
    out = []
    for r in reqs:
        q = r.need if policy_rng.random() < 0.7 else max(1, int(r.need * policy_rng.uniform(0.7, 1.0)))
        o, a = adjudicate(r, q)
        out.append((r, q, o, a))
    return out


def evaluate(seed: int = 7, target: float = 0.8, train_weeks: int = 40) -> dict:
    reqs = simulate(seed=seed)
    rng = random.Random(seed + 1)
    hist = history_from(reqs, rng)
    train = [h for h in hist if h[0].week < train_weeks]
    test = [r for r in reqs if r.week >= train_weeks and r.doc_score >= 0.3]
    m = ApprovalModel(seed).fit(train)

    X = np.array([features(r, r.need) for r in test])
    y = np.array([adjudicate(r, r.need)[0] == "approved" for r in test])
    p = m.clf.predict_proba(X)[:, 1]

    def policy(name, pick):
        full = cut = approved = lost = 0
        for r in test:
            q = pick(r)
            o, a = adjudicate(r, q)
            full += o == "approved"
            cut += o == "partial"
            approved += a
            lost += max(0, min(r.need, approvable(r)) - q) if o == "approved" else 0
        n = len(test)
        return {"policy": name, "first_pass_full": round(full / n, 3), "partial_rate": round(cut / n, 3),
                "units_approved_first_pass": approved, "units_left_on_table": lost}

    rows = [policy("ask for clinical need", lambda r: r.need),
            policy("fixed 15% haircut", lambda r: max(1, int(r.need * 0.85))),
            policy(f"model, target P(full) >= {target:.0%}", lambda r: m.recommend(r, target))]
    # calibration in 10 bins
    bins = []
    for lo in np.linspace(0, 0.9, 10):
        sel = (p >= lo) & (p < lo + 0.1)
        if sel.sum() >= 15:
            bins.append({"predicted": round(float(p[sel].mean()), 3), "observed": round(float(y[sel].mean()), 3),
                         "n": int(sel.sum())})
    return {"train_requests": len(train), "test_requests": len(test), "auc": round(float(roc_auc_score(y, p)), 3),
            "brier": round(float(brier_score_loss(y, p)), 3), "base_rate_full": round(float(y.mean()), 3),
            "policies": rows, "calibration": bins, "target": target}
