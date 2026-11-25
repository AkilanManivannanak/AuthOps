"""Follow one patient: a faxed treatment plan to a payor decision and a reauthorization date, one step at a time.

Every step reuses the real pipeline: OCR and rule-based extraction, the payor rules, the approval-outlook model,
recorded browser-agent runs, the payor's adjudication and the burn-down forecast.
"""
from __future__ import annotations

import json
import random
import tempfile
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from app.ui import ASSETS, checklist, log, rule_label
from app.widgets.outlook import approval_outlook
from app.widgets.workbench import workbench
from authops.docintel.extract import RuleExtractor
from authops.docintel.ocr import ocr_pages
from authops.intel.approval import ApprovalModel, Request, adjudicate, history_from, simulate
from authops.monitor.panel import PAYOR_TURNAROUND, forecast
from authops.schemas import DocType
from authops.synth.generate import PAYOR_BY_ID, generate_cases
from authops.validation.rules import validate_case

TODAY = date(2026, 11, 17)
STEPS = ["Intake", "Readiness check", "Submit", "Payor decision", "Monitoring"]
UNIT = {"aba": "hours", "physical_therapy": "visits", "behavioral_health": "sessions"}
SERVICE = {"aba": "ABA therapy", "physical_therapy": "Physical therapy", "behavioral_health": "Behavioral health"}
PRESETS = [("aba", "KCM", "Child, ABA therapy"), ("physical_therapy", "NWH", "Adult, physical therapy"),
           ("behavioral_health", "HBL", "Adult, behavioral health")]
ROUTE = {"portal": "Browser agent on the payor portal", "fhir": "FHIR prior authorization API", "phone": "Phone agent"}
REPLAY = {"KCM": ("keystone_aba_iframe_calendar", "summit_mfa_503_retry"), "NWH": ("northwind_popup", "summit_mfa_503_retry")}
PLAN = {"KCM": "medicaid_mco"}

CSS = """<style>
.jr-rail{display:flex;gap:0;margin:.4rem 0 1.4rem;border:1px solid #ECE5D8;border-radius:999px;overflow:hidden;background:#fff}
.jr-rail div{flex:1;padding:10px 6px;text-align:center;font-size:.84rem;color:#8E8292;position:relative;border-right:1px solid #F0EAE2}
.jr-rail div:last-child{border-right:0}.jr-rail .done{color:#5B2A86;background:#F7F1FB}.jr-rail .cur{color:#fff;background:#1E0525;font-weight:600}
.jr-rail b{font-weight:600;margin-right:6px}
.jr-pt{border:1px solid #ECE5D8;border-radius:16px;padding:14px 16px;background:#fff}
.jr-pt.on{border-color:#1E0525;box-shadow:0 10px 24px -18px rgba(30,5,37,.6);background:linear-gradient(135deg,#FDF8F3,#FAE8E8)}
.jr-pt .n{font-family:Fraunces,Georgia,serif;font-size:1.25rem}.jr-pt .m{color:#7A6B80;font-size:.85rem}
.jr-route{display:inline-flex;gap:8px;align-items:center;border-radius:999px;background:#EFE7FA;color:#5B2A86;font-weight:600;
 padding:6px 14px;font-size:.9rem}
.jr-done{font-family:Fraunces,Georgia,serif;font-size:1.6rem;line-height:1.3;margin-top:.6rem}
.jr-chip{display:inline-block;border:1px solid #ECE5D8;border-radius:12px;padding:10px 14px;background:#fff;margin-right:10px}
.jr-chip b{display:block;font-family:Fraunces,Georgia,serif;font-weight:400;font-size:1.5rem}.jr-chip span{color:#7A6B80;font-size:.8rem}
</style>"""


@st.cache_resource(show_spinner=False)
def _model():
    return ApprovalModel().fit([h for h in history_from(simulate(), random.Random(8)) if h[0].week < 40])


@st.cache_resource(show_spinner=False)
def _history():
    return history_from(simulate(), random.Random(8))


@st.cache_data(show_spinner=False)
def _preset_seed(spec: str) -> int:
    for s in range(1, 4000):
        c = generate_cases(1, seed=s, today=TODAY, gap_rate=0.0)[0]
        if c.specialty == spec:
            return s
    return 1


def _case(i: int):
    spec, pid, _ = PRESETS[i]
    c = generate_cases(1, seed=_preset_seed(spec), today=TODAY, gap_rate=0.0)[0]
    c.payor = PAYOR_BY_ID[pid]
    c.patient.member_id = pid + c.patient.member_id[3:]
    return c


@st.cache_data(show_spinner=False, max_entries=16)
def _read(pages: tuple, doc_type: str):
    ocr = ocr_pages(list(pages))
    ex = RuleExtractor().extract("doc", ocr, DocType(doc_type))
    words = [(w.text, w.conf, w.box, pi) for pi, p in enumerate(ocr.pages) for w in p.words]
    return {"fields": {k: v.model_dump() for k, v in ex.fields.items()}, "words": words, "text": ocr.text}


@st.cache_data(show_spinner=False, max_entries=8)
def _render_plan(i: int) -> list[str]:
    from authops.synth.render import render_treatment_plan, save_doc
    rng = random.Random(100 + i)
    return save_doc(render_treatment_plan(_case(i), rng, False), Path(tempfile.mkdtemp(prefix="jr_")), "tp", "fax", rng)


@st.cache_data(show_spinner=False, max_entries=16)
def _render_letter(i: int, decision: str, units: int) -> list[str]:
    import authops.synth.render as R
    orig = R.payor_decision
    R.payor_decision = lambda case, rng: (decision, units, None)
    try:
        rng = random.Random(200 + i)
        w, _, _ = R.render_letter(_case(i), rng)
        return R.save_doc(w, Path(tempfile.mkdtemp(prefix="jl_")), "letter", "fax", rng)
    finally:
        R.payor_decision = orig


def _fields(res: dict, thr: float = 0.55):
    out = []
    for name, fv in res["fields"].items():
        if name == "denial_reason":
            continue
        v, conf = fv["value"], fv["confidence"]
        status = "abstained" if (v in (None, "", []) or conf < thr) else ("sure" if conf >= 0.8 else "unsure")
        sv = None if v in (None, "", []) else str(", ".join(v) if isinstance(v, list) else v)
        boxes = []
        if sv:
            toks = {x.strip(",.:").upper() for x in sv.split()}
            if len(sv) == 10 and sv[4] == "-":
                d = date.fromisoformat(sv)
                toks |= {d.strftime("%m/%d/%Y"), d.strftime("%B").upper(), f"{d.day},", str(d.year)}
            boxes = [w[2] for w in res["words"] if w[3] == 0 and w[0].strip(",.:").upper() in toks and len(w[0]) > 1][:6]
        why = ("Read with high confidence; filled in automatically." if status == "sure" else
               "Filled in, but a person should glance at it." if status == "unsure" else
               "Too unsure to guess, so it is left for a person.")
        out.append({"key": name, "label": name.replace("_", " "), "value": None if status == "abstained" else sv,
                    "conf": float(conf), "status": status, "why": why, "boxes": boxes})
    return out


def _request(case, units: int) -> Request:
    rng = random.Random(hash(case.patient.member_id) % 10_000)
    return Request(52, case.payor.payor_id, case.specialty, round(rng.uniform(0.45, 0.8), 2), round(rng.uniform(0.7, 0.95), 2),
                   False, 0.85, units, 1.0)


def _rail(step: int) -> None:
    cells = "".join(f"<div class='{'done' if k < step else 'cur' if k == step else ''}'><b>{'✓' if k < step else k + 1}</b>{n}</div>"
                    for k, n in enumerate(STEPS))
    st.markdown(f"<div class='jr-rail'>{cells}</div>", unsafe_allow_html=True)


def _go(step: int) -> None:
    st.session_state.jr["step"] = step


def journey() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    if "jr" not in st.session_state:
        st.session_state.jr = {"pt": 0, "step": 0, "typed": {}, "gap": False, "signed": False, "fixes": set(),
                               "submitted": False, "chaos": False, "units": None}
    J = st.session_state.jr

    cols = st.columns(3)
    for i, (spec, pid, who) in enumerate(PRESETS):
        c = _case(i)
        on = J["pt"] == i
        cols[i].markdown(f"<div class='jr-pt {'on' if on else ''}'><div class='m'>{who}</div><div class='n'>{c.patient.full_name}</div>"
                         f"<div class='m'>{PAYOR_BY_ID[pid].name} · {c.requested_units} {UNIT[spec]} asked</div></div>",
                         unsafe_allow_html=True)
        if cols[i].button("Following" if on else "Follow this patient", key=f"jr_pick_{i}", disabled=on, width="stretch"):
            st.session_state.jr = {"pt": i, "step": 0, "typed": {}, "gap": False, "signed": False, "fixes": set(),
                                   "submitted": False, "chaos": False, "units": None}
            st.rerun()
    i = J["pt"]
    case = _case(i)
    if J["units"] is None:
        J["units"] = int(case.requested_units)
    _rail(J["step"])
    step = J["step"]

    # ------------------------------------------------------------ 1 intake
    if step == 0:
        st.markdown("#### The clinic faxes a treatment plan")
        pages = _render_plan(i)
        res = _read(tuple(pages), DocType.TREATMENT_PLAN.value)
        fields = _fields(res)
        workbench(pages[0], [w[2] for w in res["words"] if w[3] == 0], fields,
                  f"{sum(f['status'] != 'abstained' for f in fields)} of {len(fields)} fields filled by AI · faxed treatment plan",
                  key=f"jr_wb_{i}")
        gaps = [f for f in fields if f["status"] == "abstained"]
        if gaps:
            st.markdown("**Left for you.** The AI was too unsure to guess these. Read them off the page and type them in.")
            for f in gaps:
                J["typed"][f["key"]] = st.text_input(f["label"].capitalize(), J["typed"].get(f["key"], ""),
                                                     key=f"jr_t_{i}_{f['key']}")
        typed = sum(bool(J["typed"].get(f["key"])) for f in gaps)
        st.markdown(f"Fields filled by AI: **{len(fields) - len(gaps)} of {len(fields)}**"
                    + (f" · by you: **{typed} of {len(gaps)}**" if gaps else ""))
        if typed:
            J["fixes"].add("typed")
        st.button("Continue to the readiness check", type="primary", disabled=typed < len(gaps), on_click=_go, args=(1,))
        return

    # ------------------------------------------------------------ 2 readiness
    if step == 1:
        st.markdown("#### Check it against this payor's rules before anyone submits")
        a, b = st.columns(2)
        J["gap"] = a.toggle("Inject a documentation gap", J["gap"], help="Removes the provider's signature from the plan.")
        if J["gap"]:
            J["signed"] = b.toggle("Provider signed the plan", J["signed"])
            if J["signed"]:
                J["fixes"].add("signature")
        if case.specialty == "aba" and not case.school_schedule_attached:
            J["school"] = a.toggle("Attach the school schedule", J.get("school", False),
                                   help="This payor needs it before approving ABA hours on school days.")
            if J["school"]:
                J["fixes"].add("school")
        cc = case.model_copy(deep=True)
        cc.school_schedule_attached = case.school_schedule_attached or J.get("school", False)
        if J["gap"] and not J["signed"]:
            cc.signature_present, cc.signature_date = False, None
        cc.requested_units = J["units"]
        rep = validate_case(cc, TODAY, include_custom=False)
        am, rq = _model(), _request(case, J["units"])
        rec = am.recommend(rq, 0.8)
        p_now, p_rec = am.outlook(rq, J["units"])["p_full"], am.outlook(rq, rec)["p_full"]
        short = p_now < 0.8 and rec != J["units"]
        left, right = st.columns([1, 1.25])
        with left:
            checklist([("ok" if r.passed else "bad" if r.passed is False else "warn", rule_label(r.rule),
                        r.message or "passes") for r in rep.results]
                      + [("warn" if short else "ok", "Units this payor approves in full",
                          f"{p_now:.0%} chance at {J['units']}; {rec} gives {p_rec:.0%}" if short else f"{p_now:.0%} chance at {J['units']}")])
        with right:
            J["units"] = st.slider(f"Requested {UNIT[case.specialty]}", 1, int(case.requested_units * 1.5),
                                   J["units"], key=f"jr_units_{i}_{J['units'] if J.get('_moved') else 0}")
            J["_moved"] = False
            curve = [{"units": c["units"], "p": c["p_full"], "exp": am.outlook(rq, c["units"])["expected_units"]}
                     for c in am.curve(Request(rq.week, rq.payor, rq.specialty, rq.severity, rq.utilization, rq.first_auth,
                                               rq.doc_score, max(J["units"], rec, case.requested_units), 1.0), points=40)]
            dots = [{"q": q, "a": aa, "o": oc, "w": h.week, "s": round(h.severity, 2)} for h, q, oc, aa in _history()
                    if h.payor == rq.payor and h.specialty == case.specialty and abs(h.severity - rq.severity) <= 0.15][:120]
            approval_outlook(curve, dots, J["units"], rec, 0.8, key=f"jr_ol_{i}_{J['units']}")
        if short and st.button(f"Ask for {rec} {UNIT[case.specialty]} instead ({p_rec:.0%} chance)"):
            J["units"], J["_moved"] = rec, True
            J["fixes"].add("units")
            st.rerun()
        if not rep.ready:
            st.error(" ".join(r.message for r in rep.blocking) + " Fix it here, before the payor sees it.")
        c1, c2 = st.columns([1, 4])
        c1.button("Back", on_click=_go, args=(0,))
        c2.button("Ready to submit" if not short else "Submit anyway", type="primary", disabled=not rep.ready,
                  on_click=_go, args=(2,))
        return

    # ------------------------------------------------------------ 3 submit
    if step == 2:
        ch = case.payor.channel
        st.markdown(f"#### Send it the best way {case.payor.name} accepts")
        st.markdown(f"<span class='jr-route'>{ROUTE[ch]}</span>", unsafe_allow_html=True)
        if ch == "portal":
            J["chaos"] = st.toggle("Turn on chaos (pop-ups, session kicks, slow pages)", J["chaos"])
        if st.button("Submit", type="primary") or J["submitted"]:
            J["submitted"] = True
            log("journey_submit", {"pt": i, "units": J["units"], "chaos": J["chaos"]})
            if ch == "portal":
                from app.widgets.replay import player
                name = REPLAY[case.payor.payor_id][1 if J["chaos"] else 0]
                run = json.loads((ASSETS / "replays" / name / "run.json").read_text())
                st.caption(f"Recorded run of the browser agent on the sandbox portal: {len(run['steps'])} steps, "
                           f"{run['duration_s']}s, ending in {run['status']}.")
                player(run, ASSETS / "replays" / name)
            elif ch == "fhir":
                from authops.channels.router import build_pas_bundle
                cc = case.model_copy(deep=True)
                cc.requested_units = J["units"]
                b = build_pas_bundle(json.loads(cc.model_dump_json()))
                kinds = [e["resource"]["resourceType"] for e in b.get("entry", [])]
                st.markdown(f"Sent as one Da Vinci PAS bundle ({len(kinds)} resources: {', '.join(sorted(set(kinds)))}). "
                            "The payor answered **202 Accepted**; no portal or phone call was needed.")
            c1, c2 = st.columns([1, 4])
            c1.button("Back", on_click=_go, args=(1,))
            c2.button("See the payor's decision", type="primary", on_click=_go, args=(3,))
        return

    # ------------------------------------------------------------ 4 decision
    rq = _request(case, J["units"])
    decision, approved = adjudicate(rq, J["units"])
    if step == 3:
        st.markdown("#### The payor's letter comes back, and is read the same way")
        pages = _render_letter(i, decision, approved)
        res = _read(tuple(pages), DocType.APPROVAL_LETTER.value)
        fields = _fields(res)
        workbench(pages[0], [w[2] for w in res["words"] if w[3] == 0], fields,
                  f"{'Approved in full' if decision == 'approved' else 'Partially approved'}: {approved} of {J['units']} "
                  f"{UNIT[case.specialty]}", key=f"jr_wl_{i}_{decision}_{approved}")
        if decision == "partial":
            st.markdown(f"#### Cut to {approved} of {J['units']} {UNIT[case.specialty]}. Appeal or resubmit?")
            a, b = st.columns(2)
            mn = next((ln for ln in res["text"].splitlines() if "necessity" in ln.lower()), "")
            plan_text = _read(tuple(_render_plan(i)), DocType.TREATMENT_PLAN.value)["text"]
            mn = next((ln for ln in plan_text.splitlines() if "necessity" in ln.lower()), mn)
            a.markdown("**Resubmit later (recommended)**  \nStart care on the approved units and ask for the rest at "
                       "reauthorization with progress data. No peer-to-peer, no delay to the start of care.")
            b.markdown("**Appeal now**  \nAsk for a peer-to-peer review citing the plan's own words"
                       + (f": _\"{mn.strip()[:160]}\"_" if mn else ".") + " Care starts on the approved units meanwhile.")
            st.caption("Next time, the readiness check would have recommended the amount this payor approves in full.")
        c1, c2 = st.columns([1, 4])
        c1.button("Back", on_click=_go, args=(2,))
        c2.button("Start monitoring", type="primary", on_click=_go, args=(4,))
        return

    # ------------------------------------------------------------ 5 monitoring
    weekly = max(1.0, approved / 24)
    days = (case.end_date - case.start_date).days
    plan_type = PLAN.get(case.payor.payor_id, "commercial")
    f = forecast(approved, weekly, days, PAYOR_TURNAROUND[plan_type][1])
    start_in = max(0, f["runway_days"] - f["reauth_lead_days"])
    when = case.start_date + timedelta(days=start_in)
    st.markdown("#### Now it is watched until the next authorization")
    st.markdown(f"<span class='jr-chip'><b>{approved}</b><span>{UNIT[case.specialty]} approved</span></span>"
                f"<span class='jr-chip'><b>{f['runway_days']} days</b><span>runway ({'units run out first' if f['binding_limit'] == 'units' else 'the authorization ends first'})</span></span>"
                f"<span class='jr-chip'><b>{when:%b %d, %Y}</b><span>start the reauthorization</span></span>"
                f"<span class='jr-chip'><b>{f['reauth_lead_days']} days</b><span>this payor's slow-case turnaround plus a buffer</span></span>",
                unsafe_allow_html=True)
    fixes = len(J["fixes"])
    what = "Cleared for care" if decision == "approved" else f"Care started on {approved} of {J['units']} {UNIT[case.specialty]}"
    st.markdown(f"<div class='jr-done'>{what} in 4 steps, {fixes} fix{'es' if fixes != 1 else ''} before submission, "
                f"0 denials.</div>", unsafe_allow_html=True)
    st.page_link("app/views/insurance_monitoring.py", label="See every patient's runway", icon=":material/arrow_forward:")
    c1, c2 = st.columns([1, 4])
    c1.button("Back", on_click=_go, args=(3,))
    if c2.button("Follow the next patient", type="primary"):
        st.session_state.jr = {"pt": (i + 1) % 3, "step": 0, "typed": {}, "gap": False, "signed": False, "fixes": set(),
                               "submitted": False, "chaos": False, "units": None}
        st.rerun()
