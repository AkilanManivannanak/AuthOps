import random
from datetime import date, timedelta

import pandas as pd
import streamlit as st
import yaml

from app.ui import rule_label, Timer, checklist, log, note, pill, require_tester, setup, store
from authops.docintel.normalize import KNOWN_ICD10, SPECIALTY_CPT
from authops.llm import ClaudeLLM, llm_available
from authops.synth.generate import PAYOR_BY_ID, PAYORS, generate_cases, payor_decision
from authops.validation.engine import compile_rule
from authops.validation.rules import NLRule, load_requirements, validate_case, validate_with_graph

TODAY = date(2026, 11, 17)
setup("Denial Shield", "Build a request, see its approval odds, and catch payor rule changes as they happen.")
t = require_tester("so finding the hidden rule counts as a completed task")
req = load_requirements()

if "ds_case" not in st.session_state or st.button("Start from a new patient"):
    st.session_state.ds_case = generate_cases(1, seed=random.randint(1, 9999), today=TODAY, gap_rate=0.0)[0]
    st.session_state.ds_units = int(st.session_state.ds_case.requested_units)
    st.session_state.setdefault("ds_history", [])
    Timer("drift").reset()
st.session_state.setdefault("ds_history", [])
case = st.session_state.ds_case.model_copy(deep=True)
st.session_state.setdefault("ds_units", int(case.requested_units))

form, out = st.columns([1, 1.1])
with form:
    st.markdown("#### The request")
    a, b = st.columns(2)
    pid = a.selectbox("Payor", [p.payor_id for p in PAYORS], index=[p.payor_id for p in PAYORS].index(case.payor.payor_id),
                      format_func=lambda x: PAYOR_BY_ID[x].name)
    spec = b.selectbox("Specialty", list(SPECIALTY_CPT), index=list(SPECIALTY_CPT).index(case.specialty),
                       format_func=lambda s: s.replace("_", " ").title())
    all_cpt = sorted(set().union(*SPECIALTY_CPT.values()))
    cpts = st.multiselect("CPT codes", all_cpt, default=[c for c in case.cpt_codes if c in all_cpt])
    icds = st.multiselect("ICD-10 diagnosis codes", sorted(KNOWN_ICD10) + ["F8A.0 (typo)"],
                          default=[c for c in case.icd10_codes if c in KNOWN_ICD10])
    units = st.slider("Requested units", 1, 520, key="ds_units")
    d1, d2 = st.columns(2)
    start = d1.date_input("Plan start", case.start_date)
    end = d2.date_input("Plan end", case.end_date)
    s1, s2 = st.columns(2)
    signed = s1.toggle("Provider signed the plan", value=case.signature_present)
    school = s2.toggle("School schedule attached", value=case.school_schedule_attached)

case.payor = PAYOR_BY_ID[pid]
case.patient.member_id = pid + case.patient.member_id[3:]
case.specialty, case.cpt_codes = spec, cpts or ["97153"]
case.icd10_codes = [c.split(" ")[0] for c in icds] or ["F84.0"]
case.requested_units, case.start_date, case.end_date = units, start, end
case.signature_present, case.signature_date = signed, (TODAY - timedelta(days=3)) if signed else None
case.school_schedule_attached = school
case.injected_gaps = []

from authops.intel.approval import ApprovalModel, Request, history_from, simulate  # noqa: E402
from authops.intel.approval import evaluate as approval_evaluate  # noqa: E402


@st.cache_resource(show_spinner="Training on past decisions")
def _approval_model():
    reqs = simulate()
    return ApprovalModel().fit([h for h in history_from(reqs, random.Random(8)) if h[0].week < 40])


@st.cache_data(show_spinner=False)
def _approval_eval(target: float):
    return approval_evaluate(target=target)



OUT_PAYORS = ("NWH", "KCM", "SFB", "HBL", "PRV")


def _outlook_now():
    ss = st.session_state
    first_ = ss.get("ol_first", False)
    rq_ = Request(52, pid if pid in OUT_PAYORS else "NWH", spec, ss.get("ol_sev", 0.55),
                  0.0 if first_ else ss.get("ol_used", 0.85), first_, 0.85, units, 1.0)
    am_, tgt = _approval_model(), ss.get("ol_target", 0.8)
    rec_ = am_.recommend(rq_, tgt)
    return am_.outlook(rq_, units)["p_full"], rec_, am_.outlook(rq_, rec_)["p_full"], tgt


def _use_rec(n):
    st.session_state.ds_units = n


rep = validate_case(case, TODAY, req, include_custom=False)
p_now, rec_now, p_rec, tgt_now = _outlook_now()
short = rep.ready and p_now < tgt_now and rec_now != units
with out:
    verdict = (pill(f"Blocked: {len(rep.blocking)} issue(s)", "bad") if not rep.ready else
               pill("Documents ready, units too high", "warn") if short else pill("Ready to submit", "ok"))
    st.markdown(f"#### Rules check &nbsp; {verdict}", unsafe_allow_html=True)
    checklist([("ok" if r.passed else "bad" if r.passed is False else "warn",
                rule_label(r.rule), r.message or "passes") for r in rep.results]
              + [("warn" if short else "ok", "units this payor approves in full",
                  f"{p_now:.0%} chance of full approval at {units} units; {rec_now} units gives {p_rec:.0%}" if short
                  else f"{p_now:.0%} chance of full approval at {units} units")])
    g = validate_with_graph(case, TODAY, req)
    st.markdown(" → ".join(f"<span class='ao-pill' style='background:#F5EEFB;color:#5B2A86'>{n}</span>"
                           for n in g["path"]), unsafe_allow_html=True)
    if g["passed"] is None:
        st.caption("A plain-English rule on this path needs a model to decide, so this request would go to a person.")
    with st.popover("Write a rule"):
        q = st.text_input("Plain-English rule", "Does the plan state measurable functional goals?")
        st.caption("Compiled to the schema the model must fill. `answer` accepts only a true boolean, and a "
                   "true needs quotes that are found in the document.")
        st.json(compile_rule(q).model_json_schema(), expanded=False)

    if short:
        st.button(f"Ask for {rec_now} units instead ({p_rec:.0%} chance)", type="primary", width="stretch",
                  on_click=_use_rec, args=(rec_now,))
    if st.button("Send to the payor ", type="secondary" if short else "primary", width="stretch"):
        decision, approved, reason = payor_decision(case, random.Random(hash((pid, spec, units))))
        drift = rep.ready and decision == "denied"
        st.session_state.ds_history.insert(0, {"payor": pid, "specialty": spec, "units": units,
                                               "rules said": "ready" if rep.ready else "blocked",
                                               "payor said": decision, "reason": reason or "", "drift": drift})
        log("payor_send", {"payor": pid, "specialty": spec, "units": units, "ready": rep.ready, "decision": decision})
        if drift:
            st.balloons()
            st.success(f"Requirements drift found: the rules said ready, the payor denied it. Reason: {reason} "
                       "In production this becomes a new rule in the payor requirements database.")
            if t:
                store().task(tester_id=t["id"], task="drift_hunt", success=1, seconds=Timer("drift").seconds,
                             detail=f"{pid}/{spec}/{units}")
        elif decision == "denied":
            st.info(f"Denied, as the rules predicted: {reason}")
        else:
            st.success(f"{decision.title()} ({approved} units).")

# ---------------------------------------------------------------- approval outlook
st.markdown("#### Approval outlook")
note("Probability that the payor approves this request in full at a given unit count, learned from 40 weeks "
           "of past decisions. Asking for more than the payor will fund usually ends in a partial approval weeks "
           "later; the recommendation is the largest request that clears your target probability.")


oc1, oc2, oc3, oc4 = st.columns(4)
sev = oc1.slider("Assessment severity", 0.0, 1.0, 0.55, 0.05, key="ol_sev", help="Standardized assessment, mild (0) to severe (1).")
first = oc2.toggle("First authorization", value=False, key="ol_first")
used = oc3.slider("Last authorization used", 0.0, 1.2, 0.85, 0.05, disabled=first, key="ol_used",
                  help="Share of the previous authorization's units actually delivered.")
target = oc4.slider("Target P(full approval)", 0.5, 0.95, 0.8, 0.05, key="ol_target")
am = _approval_model()
rq = Request(52, pid if pid in ("NWH", "KCM", "SFB", "HBL", "PRV") else "NWH", spec, sev, 0.0 if first else used, first,
             0.85, units, 1.0)
o = am.outlook(rq, units)
rec = am.recommend(rq, target)
r_o = am.outlook(rq, rec)
from app.widgets.outlook import approval_outlook  # noqa: E402


@st.cache_resource(show_spinner=False)
def _approval_history():
    return history_from(simulate(), random.Random(8))


creq = Request(rq.week, rq.payor, rq.specialty, rq.severity, rq.utilization, rq.first_auth, rq.doc_score,
               max(units, rec), 1.0)
pts = []
for c in am.curve(creq, points=48):
    oo = am.outlook(rq, c["units"])
    pts.append({"units": c["units"], "p": c["p_full"], "exp": oo["expected_units"]})
dots = [{"q": q, "a": a, "o": oc, "w": h.week, "s": round(h.severity, 2)} for h, q, oc, a in _approval_history()
        if h.payor == rq.payor and h.specialty == spec and abs(h.severity - sev) <= 0.15][:160]
approval_outlook(pts, dots, units, rec, target, key=f"ol_{rq.payor}_{spec}_{units}_{sev}_{used}_{first}_{target}")
log("approval_outlook", {"payor": pid, "spec": spec, "units": units, "p": o["p_full"], "rec": rec})
with st.expander("Backtest on 12 held-out weeks"):
    ev = _approval_eval(target)
    st.dataframe(pd.DataFrame(ev["policies"]).rename(columns={
        "first_pass_full": "full approval, first pass", "partial_rate": "partial approvals",
        "units_approved_first_pass": "units approved, first pass", "units_left_on_table": "units not requested"}),
        hide_index=True, width="stretch")
    st.caption(f"{ev['test_requests']:,} test requests; AUC {ev['auc']}, Brier {ev['brier']}. The model beats a fixed "
               "haircut on both full approvals and units; against asking for the full clinical need it trades some "
               "first-pass units for far fewer partial approvals, which is why the target is a setting.")

hist = st.session_state.get("ds_history", [])
if hist:
    st.markdown("#### Your attempts")
    st.dataframe(pd.DataFrame(hist), hide_index=True, width="stretch")
    n = len(hist)
    agree = sum((h["rules said"] == "blocked") == (h["payor said"] == "denied") for h in hist)
    st.caption(f"Rules agreed with the payor on {agree} of {n} attempts.")

with st.expander("Payor requirements database (what the rules know)"):
    st.code(yaml.safe_dump({pid: req["payors"][pid]}, sort_keys=False), language="yaml")
    st.caption("Default rules for every payor: " + ", ".join(req["defaults"]))

with st.expander("Write a plain-English rule (AI yes/no)"):
    q = st.text_input("Rule", "Does the plan state measurable functional goals?")
    txt = st.text_area("Document text to check", "Goals target measurable improvement over the authorization period. "
                       "Each goal has a baseline, a mastery criterion and a review date.")
    if st.button("Evaluate rule"):
        if not llm_available():
            st.warning("Needs the AI reader to be switched on. Without it the rule returns 'could not evaluate', "
                       "which routes to a person instead of passing.")
        r = NLRule(q, ClaudeLLM() if llm_available() else None).run(case, {"documents_text": txt})
        st.markdown(pill({True: "PASS", False: "FAIL", None: "COULD NOT EVALUATE"}[r.passed],
                         {True: "ok", False: "bad", None: "warn"}[r.passed]) + f" &nbsp; {r.message}",
                    unsafe_allow_html=True)
