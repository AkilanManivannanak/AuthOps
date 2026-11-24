import altair as alt
import pandas as pd
import streamlit as st

from app.ui import FOREST, RED, asset_json, log, setup, tiles
from authops.monitor.panel import PAYOR_TURNAROUND, forecast, make_panel, simulate

setup("Coverage Monitor", "Catch lapsed coverage and expiring authorizations between visits.")

from app.widgets.coverage import coverage_board  # noqa: E402
from authops.monitor.panel import SPECIALTY  # noqa: E402

st.markdown("### Who needs a reauthorization, and when")
cb1, cb2 = st.columns([1, 3])
board_buffer = cb1.slider("Safety buffer (days)", 0, 21, 7, key="board_buffer")
coverage_board(make_panel(160, 5), SPECIALTY, {k: v[1] for k, v in PAYOR_TURNAROUND.items()}, board_buffer,
               key=f"cov_{board_buffer}")

m = asset_json("care_readiness.json") or {}
mon = m.get("monitor", {})
if mon:
    cut = mon["proactive"]["denied_dollars_cut_vs_reactive"]
    tiles([
        (mon["reactive"]["denied_dollars"], "denied dollars over 26 weeks, reacting to denials", "int", True),
        (mon["proactive"]["denied_dollars"], "denied dollars with the proactive monitor", "int", False),
        (cut[1], f"less denied revenue than reacting (range {cut[0]:.0%} to {cut[2]:.0%}, 5 seeds)", "pct0", False),
        (mon["proactive"].get("alert_precision") or 0, "share of monitor alerts that were needed", "pct", False),
    ])
    rows = []
    for pol in ("reactive", "scheduled", "proactive"):
        for cause, v in mon[pol]["by_cause"].items():
            rows.append({"policy": pol, "cause": cause.replace("_", " "), "denied visits": v})
    chart = alt.Chart(pd.DataFrame(rows)).mark_bar().encode(
        x=alt.X("denied visits:Q"), y=alt.Y("policy:N", sort=["reactive", "scheduled", "proactive"]),
        color=alt.Color("cause:N", scale=alt.Scale(range=[RED, "#E0855F", "#8C5FB9", "#1E0525"])),
        tooltip=["policy", "cause", "denied visits"]).properties(height=170)
    st.markdown("### Why visits get denied under each policy (mean of 5 seeds, 200 patients)")
    st.altair_chart(chart, width="stretch")
    st.dataframe(pd.DataFrame([{"policy": p, **{k: mon[p][k] for k in ("visits", "denied_visits", "denied_dollars",
                 "days_without_valid_auth", "reauths", "eligibility_checks", "alerts")}} for p in
                 ("reactive", "scheduled", "proactive")]), hide_index=True, width="stretch")
    st.caption("Reactive: the clinic learns from the denial about 3 weeks after the visit. Scheduled: monthly "
               "eligibility checks and reauth 14 days before the end date. Proactive: weekly eligibility checks and a "
               "unit burn-down forecast that starts the reauth when the runway is shorter than the payor's 90th "
               "percentile turnaround plus a buffer.")

st.markdown("### Run it with your own settings")
a, b, c = st.columns(3)
n = a.slider("Patients", 50, 400, 200, 50)
buffer = b.slider("Safety buffer (days)", 0, 21, 7)
seed = c.number_input("Seed", 1, 999, 1)
panel = make_panel(n, int(seed))
res = {p: simulate(panel, p, buffer_days=buffer).as_dict() for p in ("reactive", "scheduled", "proactive")}
log("monitor_run", {"n": n, "buffer": buffer, "seed": int(seed)})
cols = st.columns(3)
for col, p in zip(cols, res):
    col.metric(p.title(), f"${res[p]['denied_dollars']:,}", f"{res[p]['denied_visits']} denied visits",
               delta_color="off")
st.caption("A bigger buffer starts reauthorizations earlier: fewer lapses, more reauths that turn out early.")

st.markdown("### One authorization: when should the reauth start?")
f1, f2, f3, f4 = st.columns(4)
units_left = f1.number_input("Units left", 0, 2000, 60)
weekly = f2.number_input("Units used per week", 0.0, 200.0, 20.0)
days_left = f3.number_input("Days until the auth ends", 0, 400, 70)
plan = f4.selectbox("Payor type", list(PAYOR_TURNAROUND))
fc = forecast(int(units_left), float(weekly), int(days_left), PAYOR_TURNAROUND[plan][1])
verdict = "Start the reauthorization now" if fc["start_reauth_now"] else "Not yet"
color = RED if fc["start_reauth_now"] else FOREST
st.markdown(f"<div class='ao-tile'><b style='color:{color};font-size:1.2rem'>{verdict}</b><div class='ao-muted'>"
            f"Runway {fc['runway_days']} days, limited by the {fc['binding_limit']}. The payor's 90th percentile "
            f"turnaround plus buffer is {fc['reauth_lead_days']} days.</div></div>", unsafe_allow_html=True)
