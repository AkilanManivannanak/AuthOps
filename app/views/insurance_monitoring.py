import pandas as pd
import streamlit as st

from app.ui import asset_json, log, run_view, setup
from authops.intel.drift import DEFAULT_CHANGES, denials_avoided, detect, severity, simulate_stream
from authops.synth.generate import PAYOR_BY_ID

setup("Insurance monitoring")
from datetime import date as _date  # noqa: E402

from app.account import save, today, ws  # noqa: E402
from app.widgets.runway import runway_board  # noqa: E402
from authops import workspace as W  # noqa: E402

w, t = ws(), today()
rows = []
for p in w["patients"]:
    r = W.runway(p, t)
    if not r:
        continue
    lane = "sent" if p.get("reauth_started") else "due" if r["start_reauth_now"] else "ok"
    rows.append({"id": p["id"], "name": p["name"], "first": p["name"].split()[0], "service": W.SERVICE[p["spec"]],
                 "payor": p["payor_name"], "unit": p["unit"], "days": max(0, r["runway_days"]), "left": r["units_left"],
                 "used": r["used"], "approved": p["approved"], "lead": r["reauth_lead_days"], "lane": lane,
                 "reauth_on": f"{_date.fromisoformat(r['reauth_on']):%b %d}", "sent": p.get("reauth_started", ""),
                 "billed": r["billed_week"]})
due = [x for x in rows if x["lane"] == "due"]
pending_rules = 0
st.markdown(f"<div class='ao-big' style='margin-bottom:.8rem'><b style='font-weight:400;color:{'#C0446A' if due else '#5B2A86'}'>"
            f"{len(due)}</b> patient{'s' if len(due) != 1 else ''} need a reauthorization now"
            + (f" <span class='ao-muted' style='font-size:1rem'>· ${sum(x['billed'] for x in due):,} of care a week at risk</span>" if due else "")
            + "</div>", unsafe_allow_html=True)
st.markdown("### Every active authorization, by days of care left")
hit = runway_board(rows, st.session_state.get("focus"), key=f"rw_{len(w['activity'])}")
if hit:
    save(W.start_reauth(w, hit, t))
    st.session_state.focus = hit
    st.rerun()

# ---------------------------------------------------------------- payor rule changes
st.markdown("### Payor rule changes")
st.caption("Found by watching payor decisions as they arrive. A person approves each rule before it is enforced.")
SERVICE = {"aba": "ABA therapy", "physical_therapy": "physical therapy", "behavioral_health": "behavioral health"}


@st.cache_data(show_spinner=False)
def _alerts():
    stream = simulate_stream(seed=4)
    return stream, sorted(detect(stream, h=6.0), key=lambda a: (-severity(a), a.week_detected))


stream, alerts = _alerts()
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
        st.markdown(f"<div class='ao-card' style='min-height:190px'><div class='ao-eyebrow'>Spotted in {a.n_after} recent decisions</div>"
                    f"<div style='font-family:Fraunces,Georgia,serif;font-size:1.15rem;margin:4px 0 6px'>{head}</div>"
                    f"<div class='ao-muted'>{body}</div></div>", unsafe_allow_html=True)
        key = f"{a.payor}:{a.specialty}:{a.kind}"
        if act:
            st.caption("Looks like noise in documentation, not a policy. Flagged for a person, no rule proposed.")
        elif key in w["rules"]:
            ch = [c for c in DEFAULT_CHANGES if c.payor == a.payor and c.specialty == a.specialty]
            msg = st.session_state.get("im_msg", {}).get(key, "Rule is live.")
            if ch and ch[0].kind in ("unit_cap", "new_requirement"):
                v = next(iter(denials_avoided(stream, ch, {(a.payor, a.specialty): a.week_detected}).values()))
                msg += (f" Across this payor's history it would have stopped {v['denials_total'] - v['denials_before_auto_rule']}"
                        f" of {v['denials_total']} denials.")
            st.success(msg)
        elif st.button("Approve rule", key="im_" + key, width="stretch"):
            import re as _re
            cap = _re.search(r"(\d+)\s+(?:visits|units|hours|sessions)", a.signal) if a.kind == "denial_reason" else None
            out = W.approve_rule(w, key, a.payor, a.specialty, int(cap.group(1)) if cap else None, a.signal, t)
            st.session_state.setdefault("im_msg", {})[key] = out
            save(out)
            log("rule_approve", {"alert": key})
            st.rerun()

with st.expander("Investigate a change week by week"):
    run_view("app/views/drift.py")

with st.expander("How we know"):
    mon = (asset_json("care_readiness.json") or {}).get("monitor", {})
    if mon:
        lab = {"reactive": "Reacting to denials", "scheduled": "Monthly checks", "proactive": "This monitor"}
        st.dataframe(pd.DataFrame([{"Policy": lab[p], "Visits": round(mon[p]["visits"]), "Denied visits": round(mon[p]["denied_visits"]),
                                    "Denied dollars": round(mon[p]["denied_dollars"]),
                                    "Days without a valid auth": round(mon[p]["days_without_valid_auth"]),
                                    "Reauthorizations": round(mon[p]["reauths"]), "Eligibility checks": round(mon[p]["eligibility_checks"])}
                                   for p in ("reactive", "scheduled", "proactive")]), hide_index=True, width="stretch",
                     column_config={"Denied dollars": st.column_config.NumberColumn(format="dollar"),
                                    "Visits": st.column_config.NumberColumn(format="localized")})
    st.caption("200 sample patients over 26 weeks, mean of 5 seeds. Reacting: the clinic learns from the denial "
               "about 3 weeks after the visit. Monthly checks: eligibility each month and a reauth 14 days before the "
               "end date. This monitor: weekly eligibility checks and a burn-down forecast that starts the reauth when "
               "the runway is shorter than the payor's 90th percentile turnaround plus the buffer.")
