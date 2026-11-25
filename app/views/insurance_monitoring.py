import pandas as pd
import streamlit as st

from app.ui import asset_json, log, run_view, setup
from app.widgets.coverage import coverage_board
from authops.intel.drift import DEFAULT_CHANGES, denials_avoided, detect, severity, simulate_stream
from authops.monitor.panel import PAYOR_TURNAROUND, SPECIALTY, make_panel
from authops.synth.generate import PAYOR_BY_ID

setup("Insurance monitoring", "Between visits, every patient's coverage and authorization is watched, and so is every "
      "payor's behaviour.")

mon = (asset_json("care_readiness.json") or {}).get("monitor", {})
if mon:
    cut = mon["proactive"]["denied_dollars_cut_vs_reactive"]
    st.markdown(f"<div class='ao-big' style='margin-bottom:.8rem'><b style='font-weight:400;color:#5B2A86'>{cut[1]:.0%}</b> "
                "fewer denied dollars than finding out from denials</div>", unsafe_allow_html=True)

st.markdown("### Patients whose coverage or authorization is about to lapse")
cb1, _ = st.columns([1, 3])
buf = cb1.slider("Safety buffer (days)", 0, 21, 7, help="Extra days added to each payor's slow-case turnaround.")
coverage_board(make_panel(160, 5), SPECIALTY, {k: v[1] for k, v in PAYOR_TURNAROUND.items()}, buf, key=f"im_{buf}")

# ---------------------------------------------------------------- payor rule changes
st.markdown("### Payor rule changes")
st.caption("Found by watching payor decisions as they arrive. A person approves each rule before it is enforced.")
SERVICE = {"aba": "ABA therapy", "physical_therapy": "physical therapy", "behavioral_health": "behavioral health"}


@st.cache_data(show_spinner=False)
def _alerts():
    stream = simulate_stream(seed=4)
    return stream, sorted(detect(stream, h=6.0), key=lambda a: (-severity(a), a.week_detected))


stream, alerts = _alerts()
st.session_state.setdefault("im_ok", set())
cols = st.columns(min(4, len(alerts)) or 1)
for n, a in enumerate(alerts[:4]):
    name = PAYOR_BY_ID[a.payor].name
    sv = SERVICE.get(a.specialty, a.specialty)
    if a.kind == "turnaround":
        head, body = f"{name} slowed down", f"Decisions on {sv} now take {a.rate_after:g} days, up from {a.rate_before:g}."
    elif a.kind == "soft_cap":
        head, body = f"{name} cuts {sv} requests", f"Partial approvals rose from {a.rate_before:.0%} to {a.rate_after:.0%}: {a.signal}."
    else:
        head, body = f"New reason from {name}", f"“{a.signal}” now in {a.rate_after:.0%} of {sv} decisions."
    act = a.proposal.get("action") == "investigate"
    with cols[n % len(cols)]:
        st.markdown(f"<div class='ao-card' style='min-height:190px'><div class='ao-eyebrow'>Seen week {a.week_detected}</div>"
                    f"<div style='font-family:Fraunces,Georgia,serif;font-size:1.15rem;margin:4px 0 6px'>{head}</div>"
                    f"<div class='ao-muted'>{body}</div></div>", unsafe_allow_html=True)
        key = f"{a.payor}:{a.specialty}:{a.kind}"
        if act:
            st.caption("Looks like noise in documentation, not a policy. Flagged for a person, no rule proposed.")
        elif key in st.session_state.im_ok:
            ch = [c for c in DEFAULT_CHANGES if c.payor == a.payor and c.specialty == a.specialty]
            if ch and ch[0].kind in ("unit_cap", "new_requirement"):
                v = next(iter(denials_avoided(stream, ch, {(a.payor, a.specialty): a.week_detected}).values()))
                st.success(f"Enforced from week {a.week_detected + 1}: {v['denials_before_auto_rule']} denials before the "
                           f"rule, against {v['denials_before_manual_rule']} if found 6 weeks later.")
            else:
                st.success("Approved: it changes reauthorization lead times and the recommended units, not a block.")
        elif st.button("Approve rule", key="im_" + key, width="stretch"):
            st.session_state.im_ok.add(key)
            log("rule_approve", {"alert": key})
            st.rerun()

with st.expander("Investigate a change week by week"):
    run_view("app/views/drift.py")

with st.expander("How we know"):
    if mon:
        lab = {"reactive": "Reacting to denials", "scheduled": "Monthly checks", "proactive": "This monitor"}
        st.dataframe(pd.DataFrame([{"Policy": lab[p], "Visits": round(mon[p]["visits"]), "Denied visits": round(mon[p]["denied_visits"]),
                                    "Denied dollars": round(mon[p]["denied_dollars"]),
                                    "Days without a valid auth": round(mon[p]["days_without_valid_auth"]),
                                    "Reauthorizations": round(mon[p]["reauths"]), "Eligibility checks": round(mon[p]["eligibility_checks"])}
                                   for p in ("reactive", "scheduled", "proactive")]), hide_index=True, width="stretch",
                     column_config={"Denied dollars": st.column_config.NumberColumn(format="dollar"),
                                    "Visits": st.column_config.NumberColumn(format="localized")})
    st.caption("200 synthetic patients over 26 weeks, mean of 5 seeds. Reacting: the clinic learns from the denial "
               "about 3 weeks after the visit. Monthly checks: eligibility each month and a reauth 14 days before the "
               "end date. This monitor: weekly eligibility checks and a burn-down forecast that starts the reauth when "
               "the runway is shorter than the payor's 90th percentile turnaround plus the buffer.")
