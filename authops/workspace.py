"""A clinic's (or a family's) workspace: one shared state that every page reads and changes.

Reading a plan, fixing a gap, sending a request, getting a decision, approving a payor rule and starting a
reauthorization all change the same patient records, so the dashboard, the prior-auth flow, the runway and the
suggestions always agree. Pure functions over a JSON-able dict; the app saves it per account.
"""
from __future__ import annotations

import random
import time
from datetime import date, timedelta

from authops.intel.approval import ApprovalModel, Request, adjudicate, history_from, simulate
from authops.monitor.panel import PAYOR_TURNAROUND, SPECIALTY, forecast
from authops.synth.generate import PAYOR_BY_ID, generate_cases
from authops.validation.rules import validate_case

UNIT = {"aba": "hours", "physical_therapy": "visits", "behavioral_health": "sessions"}
UNIT1 = {"aba": "hour", "physical_therapy": "visit", "behavioral_health": "session"}
SERVICE = {"aba": "ABA therapy", "physical_therapy": "Physical therapy", "behavioral_health": "Behavioral health"}
PLAN = {"KCM": "medicaid_mco"}
FIX = {"signature_present": ("Get the provider's signature", "Unsigned treatment plan"),
       "school_schedule": ("Attach the school schedule", "School schedule missing"),
       "plan_not_expired": ("Update the plan dates", "Plan dates have passed"),
       "units_within_payor_limit": ("Lower to the payor's limit", "Above the payor's unit limit"),
       "rule": ("Lower to the new limit", "Above a new payor limit")}
STAGE_LABEL = {"intake": "New document", "check": "Action required", "ready": "Ready to send",
               "submitted": "Waiting on payor", "approved": "Clear for care", "partial": "Clear for care",
               "denied": "Denied"}
_MODEL: ApprovalModel | None = None


def model() -> ApprovalModel:
    global _MODEL
    if _MODEL is None:
        _MODEL = ApprovalModel().fit([h for h in history_from(simulate(), random.Random(8)) if h[0].week < 40])
    return _MODEL


# ------------------------------------------------------------------ records

def case_for(p: dict):
    c = generate_cases(1, seed=p["seed"], today=date.fromisoformat(p["anchor"]), gap_rate=0.0)[0]
    c.payor = PAYOR_BY_ID[p["payor"]]
    c.patient.member_id = p["payor"] + c.patient.member_id[3:]
    m = p.get("mods", {})
    if "signed" in m:
        c.signature_present = m["signed"]
        c.signature_date = (date.fromisoformat(p["anchor"]) - timedelta(days=3)) if m["signed"] else None
    if "school" in m:
        c.school_schedule_attached = m["school"]
    if "start" in m:
        c.start_date, c.end_date = date.fromisoformat(m["start"]), date.fromisoformat(m["end"])
    c.requested_units = p["units"]
    return c


def _request(p: dict, units: int) -> Request:
    rng = random.Random(p["seed"])
    return Request(52, p["payor"], p["spec"], round(rng.uniform(0.45, 0.8), 2), round(rng.uniform(0.7, 0.95), 2),
                   False, 0.85, units, 1.0)


def outlook(p: dict) -> dict:
    m, rq = model(), _request(p, p["units"])
    rec = m.recommend(rq, 0.8)
    return {"p_full": m.outlook(rq, p["units"])["p_full"], "recommended": rec, "p_rec": m.outlook(rq, rec)["p_full"]}


def issues(p: dict, ws: dict, today: date) -> list[dict]:
    rep = validate_case(case_for(p), today, include_custom=True)
    out = [{"code": "school_schedule" if "school" in r.rule else r.rule,
            "text": FIX.get("school_schedule" if "school" in r.rule else r.rule, (None, r.message))[1],
            "detail": r.message} for r in rep.blocking]
    for key, r in ws.get("rules", {}).items():
        if r.get("approved") and p["payor"] == r["payor"] and p["spec"] == r["spec"] and p["units"] > r["cap"]:
            out.append({"code": "rule", "text": f"Above {PAYOR_BY_ID[p['payor']].name}'s new {r['cap']}-{UNIT1[p['spec']]} limit",
                        "detail": r["text"], "cap": r["cap"]})
    return out


def runway(p: dict, today: date) -> dict | None:
    if p["stage"] not in ("approved", "partial") or not p.get("approved"):
        return None
    start, end = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
    s = SPECIALTY[p["spec"]]
    weeks = max(1.0, (end - start).days / 7)
    weekly = p["approved"] / weeks * p.get("pace", 1.0)   # the plan spreads its units over the period
    used = min(p["approved"], max(0.0, (today - start).days / 7 * weekly))
    f = forecast(int(p["approved"] - used), weekly, max(0, (end - today).days),
                 PAYOR_TURNAROUND[PLAN.get(p["payor"], "commercial")][1])
    f.update({"units_left": int(p["approved"] - used), "used": int(used), "weekly": weekly,
              "reauth_on": (today + timedelta(days=max(0, f["runway_days"] - f["reauth_lead_days"]))).isoformat(),
              "billed_week": round(s["visits"] * s["rate"])})
    return f


def status(p: dict, ws: dict, today: date) -> dict:
    """What a person should see for this patient right now."""
    if p["stage"] == "check":
        iss = issues(p, ws, today)
        return {"label": "Action required", "tone": "warn", "detail": iss[0]["text"] if iss else "Check the request"}
    if p["stage"] in ("approved", "partial"):
        r = runway(p, today)
        if p.get("reauth_started"):
            return {"label": "Reauth sent", "tone": "info", "detail": "Waiting on the payor"}
        if r and r["start_reauth_now"]:
            return {"label": "Reauth due", "tone": "warn", "detail": f"{max(0, r['runway_days'])} days of care left"}
        return {"label": "Clear for care", "tone": "ok", "detail": f"{r['runway_days']} days of runway" if r else ""}
    if p["stage"] == "denied":
        return {"label": "Denied", "tone": "bad", "detail": "Appeal or correct and resend"}
    return {"label": STAGE_LABEL[p["stage"]], "tone": "info" if p["stage"] == "submitted" else "neutral",
            "detail": {"intake": "Plan received, not read yet", "ready": "Passed every check",
                       "submitted": f"Sent {p.get('submitted_on', '')}"}.get(p["stage"], "")}


# ------------------------------------------------------------------ seeding

def _patient(seed: int, spec: str, payor: str, stage: str, today: date, **kw) -> dict:
    c = generate_cases(1, seed=seed, today=today, gap_rate=0.0)[0]
    p = {"id": f"P{seed:04d}", "seed": seed, "anchor": today.isoformat(), "name": c.patient.full_name, "spec": spec,
         "payor": payor, "payor_name": PAYOR_BY_ID[payor].name, "units": int(c.requested_units), "unit": UNIT[spec],
         "start": c.start_date.isoformat(), "end": c.end_date.isoformat(), "stage": stage, "mods": {}, "log": []}
    p.update(kw)
    return p


def new_workspace(role: str, name: str = "", seed: int = 1, today: date | None = None) -> dict:
    today = today or date.today()
    rng = random.Random(seed)
    ws = {"role": role, "name": name, "created": today.isoformat(), "patients": [], "rules": {}, "letters": [],
          "plans": [], "reviews": 0, "activity": [], "seen": {}}
    if role == "patient":
        return ws
    want = []
    for spec, payor in (("aba", "KCM"), ("physical_therapy", "NWH"), ("behavioral_health", "HBL"),
                        ("physical_therapy", "KCM"), ("aba", "SFB"), ("behavioral_health", "PRV")):
        want.append((spec, payor))
    seeds, s = {}, rng.randint(1, 5000)
    while len(seeds) < 20:   # find case seeds that produce each specialty
        c = generate_cases(1, seed=s, today=today, gap_rate=0.0)[0]
        seeds.setdefault(c.specialty, []).append(s) if len(seeds.get(c.specialty, [])) < 8 else None
        s += 1
        if sum(len(v) for v in seeds.values()) >= 24:
            break
    pool = {k: list(v) for k, v in seeds.items()}
    plan = (["intake"] * 3 + ["check"] * 4 + ["ready"] * 3 + ["submitted"] * 3 + ["approved"] * 6 + ["denied"])
    for i, stage in enumerate(plan):
        spec, payor = want[i % len(want)]
        sd = pool[spec].pop(0)
        p = _patient(sd, spec, payor, stage, today)
        if stage == "check":
            p["mods"] = [{"signed": False}, {"school": False}, {"start": (today - timedelta(days=200)).isoformat(),
                                                                   "end": (today - timedelta(days=10)).isoformat()},
                         {"signed": False}][i % 4] if spec != "aba" or i % 4 != 1 else {"school": False}
        if stage == "check" and not issues(p, {"rules": {}}, today):
            p["mods"] = {"signed": False}
        if stage == "ready" and spec == "physical_therapy" and payor == "KCM":
            p["units"] = max(p["units"], 24)   # Keystone is about to cap PT at 20; this one will be caught
        if stage == "submitted":
            p["submitted_on"] = (today - timedelta(days=rng.randint(2, 9))).isoformat()
            _decide(p)
        if stage in ("approved", "denied"):
            dur = SPECIALTY[spec]["auth_weeks"] * 7
            back = int(dur * [0.15, 0.35, 0.5, 0.65, 0.88, 0.93][i % 6]) if stage == "approved" else 12
            p["pace"] = [1.0, 1.05, 0.95, 1.1, 1.0, 1.15][i % 6]
            p["start"] = (today - timedelta(days=back)).isoformat()
            p["end"] = (today - timedelta(days=back) + timedelta(days=dur)).isoformat()
            _decide(p)
            if stage == "approved":
                p["stage"] = p["_decision"]["decision"] if p["_decision"]["decision"] != "denied" else "approved"
                p["approved"] = p["_decision"]["approved"] or p["units"]
                p["decided_on"] = p["start"]
            else:
                p["decided_on"] = (today - timedelta(days=5)).isoformat()
                p["denial"] = "Documentation does not show the patient's specific deficits."
        ws["patients"].append(p)
    activity(ws, "Workspace opened with your clinic's current requests", "care_readiness")
    return ws


def _decide(p: dict) -> None:
    d, a = adjudicate(_request(p, p["units"]), p["units"])
    p["_decision"] = {"decision": d, "approved": a}


# ------------------------------------------------------------------ actions (each returns a short message)

def activity(ws: dict, text: str, page: str = "") -> None:
    ws["activity"].insert(0, {"ts": time.time(), "text": text, "page": page})
    del ws["activity"][40:]


def find(ws: dict, pid: str) -> dict:
    return next(p for p in ws["patients"] if p["id"] == pid)


def read(ws: dict, pid: str, today: date) -> str:
    p = find(ws, pid)
    if p["stage"] == "intake":
        p["stage"] = "check" if issues(p, ws, today) else "ready"
        activity(ws, f"Read {p['name']}'s treatment plan", "prior_authorizations")
    return f"{p['name']}: " + ("needs a fix before sending." if p["stage"] == "check" else "ready to send.")


def fix(ws: dict, pid: str, code: str, today: date, value=None) -> str:
    p = find(ws, pid)
    if code == "signature_present":
        p["mods"]["signed"] = True
    elif code == "school_schedule":
        p["mods"]["school"] = True
    elif code == "plan_not_expired":
        p["mods"]["start"], p["mods"]["end"] = today.isoformat(), (today + timedelta(days=180)).isoformat()
        p["start"], p["end"] = p["mods"]["start"], p["mods"]["end"]
    elif code in ("units_within_payor_limit", "rule"):
        p["units"] = int(value or p["units"])
    left = issues(p, ws, today)
    if not left and p["stage"] in ("check", "ready"):
        p["stage"] = "ready"
    activity(ws, f"Fixed {p['name']}: {FIX.get(code, (code,))[0].lower()}", "prior_authorizations")
    return "Fixed. " + ("Ready to send." if not left else f"{len(left)} more to fix.")


def set_units(ws: dict, pid: str, units: int, today: date) -> None:
    p = find(ws, pid)
    p["units"] = int(units)
    if p["stage"] in ("check", "ready"):
        p["stage"] = "check" if issues(p, ws, today) else "ready"


def submit(ws: dict, pid: str, today: date) -> str:
    p = find(ws, pid)
    p.update({"stage": "submitted", "submitted_on": today.isoformat()})
    _decide(p)
    activity(ws, f"Sent {p['name']}'s request to {p['payor_name']}", "prior_authorizations")
    return f"Sent to {p['payor_name']}."


def receive(ws: dict, pid: str, today: date) -> str:
    p = find(ws, pid)
    d = p.get("_decision") or {"decision": "approved", "approved": p["units"]}
    p["stage"], p["decided_on"] = d["decision"], today.isoformat()
    if d["decision"] != "denied":
        p["approved"] = d["approved"]
        span = (date.fromisoformat(p["end"]) - date.fromisoformat(p["start"])).days
        p["start"], p["end"] = today.isoformat(), (today + timedelta(days=span)).isoformat()
        p.pop("reauth_started", None)
    else:
        p["denial"] = "The payor needs more documentation."
    activity(ws, f"{p['payor_name']} {d['decision'].replace('partial', 'partly approved')} {p['name']}'s request",
             "prior_authorizations")
    return {"approved": "Approved in full.", "partial": f"Approved {d['approved']} of {p['units']} {p['unit']}.",
            "denied": "Denied."}[d["decision"]]


def start_reauth(ws: dict, pid: str, today: date) -> str:
    p = find(ws, pid)
    p["reauth_started"] = today.isoformat()
    activity(ws, f"Started {p['name']}'s reauthorization", "insurance_monitoring")
    return f"Reauthorization started for {p['name']}."


def approve_rule(ws: dict, key: str, payor: str, spec: str, cap: int | None, text: str, today: date) -> str:
    ws["rules"][key] = {"payor": payor, "spec": spec, "cap": cap or 10**6, "text": text, "approved": today.isoformat()}
    if cap is None:
        activity(ws, f"Approved a new {PAYOR_BY_ID[payor].name} requirement: {text}", "insurance_monitoring")
        return "Rule live. It is checked on every new request to this payor."
    hit = []
    for p in ws["patients"]:
        if p["stage"] in ("ready", "intake", "check") and p["payor"] == payor and p["spec"] == spec and p["units"] > cap:
            if p["stage"] != "intake":
                p["stage"] = "check"
            hit.append(p["name"])
    activity(ws, f"Approved {PAYOR_BY_ID[payor].name}'s {cap}-{UNIT1[spec]} limit" +
             (f"; held {', '.join(hit)}" if hit else ""), "insurance_monitoring")
    return (f"Rule live. {len(hit)} request{'s' if len(hit) != 1 else ''} held before sending: {', '.join(hit)}."
            if hit else "Rule live. No open requests are affected.")


# ------------------------------------------------------------------ summaries and suggestions

def metrics(ws: dict, today: date) -> dict:
    P = ws["patients"]
    st = [status(p, ws, today)["label"] for p in P]
    at_risk = sum((runway(p, today) or {}).get("billed_week", 0) for p in P
                  if status(p, ws, today)["label"] == "Reauth due")
    return {"patients": len(P), "action": st.count("Action required") + st.count("Reauth due") + st.count("Denied"),
            "ready": st.count("Ready to send"), "waiting": st.count("Waiting on payor") + st.count("Reauth sent"),
            "clear": st.count("Clear for care") + st.count("Reauth due") + st.count("Reauth sent"),
            "new": st.count("New document"), "at_risk_week": at_risk}


def suggestions(ws: dict, today: date, limit: int = 3) -> list[dict]:
    """What to do next, most urgent first. Each item names a page and the patient to open there."""
    out = []
    if ws["role"] == "patient":
        for L in ws.get("letters", [])[:2]:
            if L.get("decision") == "denied":
                out.append({"title": "Plan your appeal", "body": f"{L.get('summary', '')} Deadline: {L.get('deadline') or 'see the letter'}.",
                            "page": "try_it", "cta": "Open my letter"})
        if not ws.get("letters"):
            out.append({"title": "Read your insurance letter", "body": "Upload a photo of it and get the decision, the dates and what to do next.",
                        "page": "try_it", "cta": "Upload a letter"})
        out.append({"title": "Check what your visits will cost", "body": "Estimate your share from your plan's deductible and copay.",
                    "page": "benefit_checks", "cta": "Estimate my cost", "params": {"bc": "Cost calculator"}})
        return out[:limit]
    rank = []
    for p in ws["patients"]:
        s = status(p, ws, today)
        if s["label"] == "Reauth due":
            rank.append((0, {"title": f"Start {p['name']}'s reauthorization", "body": f"{s['detail']}; {p['payor_name']} takes up to "
                             f"{runway(p, today)['reauth_lead_days']} days to decide.", "page": "insurance_monitoring", "pid": p["id"],
                             "cta": "Start reauth"}))
        elif s["label"] == "Denied":
            rank.append((1, {"title": f"Answer {p['name']}'s denial", "body": p.get("denial", ""), "page": "prior_authorizations",
                             "pid": p["id"], "cta": "Appeal or fix", "params": {"tool": "Appeal a denial"}}))
        elif s["label"] == "Action required":
            rank.append((2, {"title": f"Fix {p['name']}'s request", "body": s["detail"] + ".", "page": "prior_authorizations",
                             "pid": p["id"], "cta": "Fix it"}))
        elif s["label"] == "Ready to send":
            rank.append((3, {"title": f"Send {p['name']}'s request", "body": f"Passed every check for {p['payor_name']}.",
                             "page": "prior_authorizations", "pid": p["id"], "cta": "Send"}))
        elif s["label"] == "Waiting on payor" and (today - date.fromisoformat(p["submitted_on"])).days >= 3:
            rank.append((4, {"title": f"Check {p['name']}'s decision", "body": f"Sent {p['submitted_on']}.", "page": "prior_authorizations",
                             "pid": p["id"], "cta": "Check now"}))
        elif s["label"] == "New document":
            rank.append((5, {"title": f"Read {p['name']}'s plan", "body": "A new treatment plan arrived.", "page": "prior_authorizations",
                             "pid": p["id"], "cta": "Read it"}))
    ops = ws["role"] == "ops"   # an operations person's own work comes before the clinic's queue
    if not ws.get("rules"):
        rank.append((-0.5 if ops else 2.5, {"title": "Approve a payor rule change", "body": "Keystone started limiting physical therapy "
                           "to 20 visits. Approve it so open requests are held before they are denied.",
                           "page": "insurance_monitoring", "cta": "Review it"}))
    if ops and ws.get("reviews", 0) < 5:
        rank.append((-1, {"title": "Review what the AI read", "body": "Spot-check extracted fields; your verdicts decide "
                           "how much the agents can send on their own.", "page": "ai_ops_desk", "cta": "Start reviewing",
                           "params": {"desk": "Review"}}))
    rank.sort(key=lambda x: x[0])
    return [r for _, r in rank][:limit]
