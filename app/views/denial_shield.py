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

# ---------------------------------------------------------------- policy drift monitor
st.divider()
st.markdown("### Policy drift monitor")
st.caption("Watches every payor decision as it arrives. A sustained shift in a denial reason, a denial reason never "
           "seen before, partial approvals clustering on one value, or slower decisions raise an alert with a "
           "proposed rule and its evidence. A person approves the rule before it reaches validation.")

import altair as alt  # noqa: E402

from authops.intel.drift import DEFAULT_CHANGES, denials_avoided, detect, evaluate, match, simulate_stream  # noqa: E402


@st.cache_data(show_spinner=False)
def _drift_eval(h: float):
    return evaluate(seeds=20, h=h)


@st.cache_data(show_spinner=False)
def _stream(seed: int):
    return simulate_stream(seed=seed)


c1, c2, c3 = st.columns(3)
dseed = c1.number_input("Decision stream", 1, 500, 4, help="Each number is a different 26-week stream.")
h = c2.slider("Alarm threshold", 3.0, 9.0, 6.0, 0.5, help="Lower alarms sooner and more often.")
upto = c3.slider("Replay through week", 6, 25, 25)
stream = _stream(int(dseed))
alerts = [a for a in detect([d for d in stream if d.week <= upto], h=h)]
log("drift_monitor", {"seed": int(dseed), "h": h, "week": upto, "alerts": len(alerts)})

ev = _drift_eval(h)
k1, k2, k3, k4 = st.columns(4)
k1.metric("Changes detected (20 streams)", f"{sum(ev['detection_rate'].values()) / 4:.0%}")
k2.metric("Median weeks to detect", max(v for v in ev["median_delay_weeks"].values() if v is not None))
k3.metric("False alarms per 26 weeks", ev["false_alarms_per_26_weeks"])
k4.metric("Denials before the rule is live", f"{ev['denials_before_rule']['automatic']:,}",
          f"vs {ev['denials_before_rule']['manual_6_weeks']:,} with 6-week manual discovery", delta_color="off")

if not alerts:
    st.info(f"No alerts through week {upto}.")
else:
    rows = [{"week": a.week_detected, "payor": a.payor, "specialty": a.specialty.replace("_", " "),
             "signal": a.signal, "before": a.rate_before, "after": a.rate_after, "trigger": a.evidence}
            for a in alerts]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    pick = st.selectbox("Review alert", range(len(alerts)),
                        format_func=lambda i: f"week {alerts[i].week_detected} · {alerts[i].payor} "
                                              f"{alerts[i].specialty.replace('_', ' ')} · {alerts[i].signal[:60]}")
    a = alerts[pick]
    left, right = st.columns([1.3, 1])
    pair = [d for d in stream if d.payor == a.payor and d.specialty == a.specialty]
    weeks = sorted({d.week for d in pair})
    if a.kind == "turnaround":
        ser = [{"week": w, "value": sum(d.days_to_decision for d in pair if d.week == w) /
                max(1, sum(d.week == w for d in pair))} for w in weeks]
        ytitle = "mean days to decision"
    elif a.kind == "soft_cap":
        ser = [{"week": w, "value": sum(d.outcome == "partial" for d in pair if d.week == w) /
                max(1, sum(d.week == w for d in pair))} for w in weeks]
        ytitle = "partial approval rate"
    else:
        ser = [{"week": w, "value": sum(d.reason == a.signal for d in pair if d.week == w) /
                max(1, sum(d.week == w for d in pair))} for w in weeks]
        ytitle = "share denied for this reason"
    df = pd.DataFrame(ser)
    line = alt.Chart(df).mark_line(point=True, color="#28543E").encode(
        x=alt.X("week:Q", scale=alt.Scale(domain=[0, 25])), y=alt.Y("value:Q", title=ytitle))
    marks = pd.DataFrame([{"week": a.week_estimated, "what": "estimated start"},
                          {"week": a.week_detected, "what": "alert"}])
    rule = alt.Chart(marks).mark_rule(strokeDash=[4, 3]).encode(
        x="week:Q", color=alt.Color("what:N", scale=alt.Scale(range=["#C98B1E", "#B3402F"])), tooltip=["what", "week"])
    left.altair_chart((line + rule).properties(height=260), use_container_width=True)
    right.markdown(f"**{a.payor} · {a.specialty.replace('_', ' ')}**  \n{a.signal}")
    right.markdown(f"Rate {a.rate_before:.1%} before, {a.rate_after:.1%} since week {a.week_estimated} "
                   f"({a.n_after} decisions). Trigger: {a.evidence}.")
    if a.examples:
        right.caption("Example decisions: " + ", ".join(a.examples))
    right.markdown("**Proposed change to the requirements database**")
    right.code(yaml.safe_dump({"payors": {a.payor: {"specialties": a.proposal["specialties"]}}}, sort_keys=False),
               language="yaml")
    right.caption(a.proposal.get("note", ""))
    st.session_state.setdefault("drift_approved", {})
    key = f"{dseed}:{a.payor}:{a.specialty}:{a.signal}"
    if right.button("Approve rule", key="approve_" + key):
        st.session_state.drift_approved[key] = a.week_detected
        log("drift_approve", {"alert": key})
    if key in st.session_state.drift_approved:
        ch = [c for c in DEFAULT_CHANGES if c.payor == a.payor and c.specialty == a.specialty]
        if ch and ch[0].kind in ("unit_cap", "new_requirement"):
            da = denials_avoided(stream, ch, {(a.payor, a.specialty): a.week_detected})
            v = next(iter(da.values()))
            right.success(f"Rule live from week {a.week_detected + 1}. Denials for this change: "
                          f"{v['denials_before_auto_rule']} before the rule vs {v['denials_before_manual_rule']} "
                          f"if it had been found 6 weeks after the change; {v['denials_total']} would occur with no rule.")
        else:
            right.success("Approved. Turnaround and soft-cap changes update reauthorization lead time and the "
                          "requested-units recommendation rather than blocking a request.")
    with st.expander("Answer key for this stream"):
        m = match(alerts, DEFAULT_CHANGES)
        st.dataframe(pd.DataFrame(m["changes"]), hide_index=True, use_container_width=True)
        st.caption(f"Alerts that match no planted change: {m['false_alarms']}. " +
                   "; ".join(m["false_alarm_detail"]))
