import random
from datetime import date, timedelta

import pandas as pd
import streamlit as st
import yaml

from app.ui import Timer, checklist, log, pill, require_tester, setup, store
from authops.docintel.normalize import KNOWN_ICD10, SPECIALTY_CPT
from authops.llm import ClaudeLLM, llm_available
from authops.synth.generate import PAYOR_BY_ID, PAYORS, generate_cases, payor_decision
from authops.validation.rules import NLRule, load_requirements, validate_case

TODAY = date(2026, 11, 17)
setup("Denial Shield",
      "Build a prior-auth request and watch the payor rules check it live. Then send it to the simulated payor. "
      "One payor changed a policy that the rules database has not caught up with. Can you find it?")
t = require_tester("so finding the hidden rule counts as a completed task")
req = load_requirements()

if "ds_case" not in st.session_state or st.button("Start from a new patient"):
    st.session_state.ds_case = generate_cases(1, seed=random.randint(1, 9999), today=TODAY, gap_rate=0.0)[0]
    st.session_state.setdefault("ds_history", [])
    Timer("drift").reset()
st.session_state.setdefault("ds_history", [])
case = st.session_state.ds_case.model_copy(deep=True)

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
    units = st.slider("Requested units", 1, 520, int(case.requested_units))
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

rep = validate_case(case, TODAY, req, include_custom=False)
with out:
    verdict = pill("Ready to submit", "ok") if rep.ready else pill(f"Blocked: {len(rep.blocking)} issue(s)", "bad")
    st.markdown(f"#### Rules check &nbsp; {verdict}", unsafe_allow_html=True)
    checklist([("ok" if r.passed else "bad" if r.passed is False else "warn",
                r.rule.replace("_", " "), r.message or "passes") for r in rep.results])

    if st.button("Send to the payor (simulated)", type="primary", use_container_width=True):
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

hist = st.session_state.get("ds_history", [])
if hist:
    st.markdown("#### Your attempts")
    st.dataframe(pd.DataFrame(hist), hide_index=True, use_container_width=True)
    n = len(hist)
    agree = sum((h["rules said"] == "blocked") == (h["payor said"] == "denied") for h in hist)
    st.caption(f"Rules agreed with the payor on {agree} of {n} attempts.")

with st.expander("Payor requirements database (what the rules know)"):
    st.code(yaml.safe_dump({pid: req["payors"][pid]}, sort_keys=False), language="yaml")
    st.caption("Default rules for every payor: " + ", ".join(req["defaults"]))

with st.expander("Write a plain-English rule (LLM yes/no)"):
    q = st.text_input("Rule", "Does the plan state measurable functional goals?")
    txt = st.text_area("Document text to check", "Goals target measurable improvement over the authorization period. "
                       "Each goal has a baseline, a mastery criterion and a review date.")
    if st.button("Evaluate rule"):
        if not llm_available():
            st.warning("Needs ANTHROPIC_API_KEY in the app secrets. Without it the rule returns 'could not evaluate', "
                       "which routes to a person instead of passing.")
        r = NLRule(q, ClaudeLLM() if llm_available() else None).run(case, {"documents_text": txt})
        st.markdown(pill({True: "PASS", False: "FAIL", None: "COULD NOT EVALUATE"}[r.passed],
                         {True: "ok", False: "bad", None: "warn"}[r.passed]) + f" &nbsp; {r.message}",
                    unsafe_allow_html=True)
