import altair as alt
import pandas as pd
import streamlit as st
import yaml

from app.ui import log, note, setup
from authops.intel.drift import DEFAULT_CHANGES, denials_avoided, detect, evaluate, match, severity, simulate_stream

setup("Payor rule changes", "Payor decisions are watched as they arrive; a sustained shift becomes a proposed rule.")
# ---------------------------------------------------------------- policy drift monitor
note("Watches every payor decision as it arrives. A sustained shift in a denial reason, a denial reason never "
           "seen before, partial approvals clustering on one value, or slower decisions raise an alert with a "
           "proposed rule and its evidence. A person approves the rule before it reaches validation.")



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
    alerts = sorted(alerts, key=lambda a: (-severity(a), a.week_detected))
    level = {4: "new rule", 3: "soft cap", 2: "turnaround", 1: "investigate"}
    rows = [{"priority": level[severity(a)], "week": a.week_detected, "payor": a.payor,
             "specialty": a.specialty.replace("_", " "), "signal": a.signal, "before": f"{a.rate_before:.1%}"
             if a.kind != "turnaround" else f"{a.rate_before} d", "after": f"{a.rate_after:.1%}"
             if a.kind != "turnaround" else f"{a.rate_after} d", "trigger": a.evidence} for a in alerts]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
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
    line = alt.Chart(df).mark_line(point=True, color="#5B2A86").encode(
        x=alt.X("week:Q", scale=alt.Scale(domain=[0, 25])), y=alt.Y("value:Q", title=ytitle))
    marks = pd.DataFrame([{"week": a.week_estimated, "what": "estimated start"},
                          {"week": a.week_detected, "what": "alert"}])
    rule = alt.Chart(marks).mark_rule(strokeDash=[4, 3]).encode(
        x="week:Q", color=alt.Color("what:N", scale=alt.Scale(range=["#E0855F", "#C0446A"])), tooltip=["what", "week"])
    left.altair_chart((line + rule).properties(height=260), width="stretch")
    right.markdown(f"**{a.payor} · {a.specialty.replace('_', ' ')}**  \n{a.signal}")
    if a.kind == "turnaround":
        right.markdown(f"Mean {a.rate_before} days to decision before, {a.rate_after} since week {a.week_estimated} "
                       f"({a.n_after} decisions). Trigger: {a.evidence}.")
    else:
        right.markdown(f"Rate {a.rate_before:.1%} before, {a.rate_after:.1%} since week {a.week_estimated} "
                       f"({a.n_after} decisions). Trigger: {a.evidence}.")
    if a.examples:
        right.caption("Example decisions: " + ", ".join(a.examples))
    if a.proposal.get("action") == "investigate":
        right.markdown("**Recommended action: investigate, no new rule**")
    else:
        right.markdown("**Proposed change to the requirements database**")
        right.code(yaml.safe_dump({"payors": {a.payor: {"specialties": a.proposal["specialties"]}}}, sort_keys=False),
                   language="yaml")
    right.caption(a.proposal.get("note", ""))
    st.session_state.setdefault("drift_approved", {})
    key = f"{dseed}:{a.payor}:{a.specialty}:{a.signal}"
    if a.proposal.get("action") != "investigate" and right.button("Approve rule", key="approve_" + key):
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
        st.dataframe(pd.DataFrame(m["changes"]), hide_index=True, width="stretch")
        st.caption(f"Alerts that match no planted change: {m['false_alarms']}. " +
                   "; ".join(m["false_alarm_detail"]))
