import random

import streamlit as st

from app.ui import asset_json, log, run_view, setup, switch
from authops.benefits.calls import FIELDS, estimate, extract_careful, make_calls, readback

setup("Benefit checks", "One phone call to the payor becomes one accurate patient cost quote.")

LABEL = {"plan_active": "Plan active", "in_network": "In network", "deductible": "Deductible",
         "deductible_met": "Deductible met", "coinsurance_pct": "Coinsurance", "copay": "Copay per visit",
         "oop_max": "Out-of-pocket max", "oop_met": "Out-of-pocket met", "visit_limit": "Visit limit",
         "visits_used": "Visits used", "auth_required": "Prior auth required", "carve_out_vendor": "Carved out to"}
MONEY = {"deductible", "deductible_met", "copay", "oop_max", "oop_met"}
SERVICE = {"aba": "ABA therapy", "physical_therapy": "Physical therapy", "behavioral_health": "Behavioral health"}


def fmt(f, v):
    if v is None:
        return "None" if f == "carve_out_vendor" else "No limit"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if f in MONEY:
        return f"${v:,}"
    return f"{v}%" if f == "coinsurance_pct" else str(v)


def money(e):
    return "Vendor quote" if e["patient_total"] is None else f"${e['patient_total']:,.2f}"


@st.cache_data(show_spinner=False)
def _calls():
    out = []
    for k, c in enumerate(make_calls(n=120)):
        careful = extract_careful(c)
        fixed, _ = readback(c, careful, random.Random(1000 + k))
        wrong = [f for f in FIELDS if careful[f] != getattr(c.truth, f)]
        if wrong and c.truth.carve_out_vendor is None:
            out.append((k, c, careful, fixed))
    return out


calls = _calls()
TOOLS = {"Phone benefit check": None, "Watch a status call": "app/views/phone_agent.py",
         "Cost calculator": "cost"}
pick = switch(TOOLS, "bc")
if pick == "Phone benefit check":
    st.session_state.setdefault("bc_i", 0)
    c1, c2 = st.columns([4, 1])
    if c2.button("Another call", width="stretch"):
        st.session_state.bc_i = (st.session_state.bc_i + 1) % len(calls)
    k, c, careful, fixed = calls[st.session_state.bc_i]
    names = ["Avery Brooks", "Maya Ortiz", "Jordan Lee", "Sam Patel", "Riley Chen", "Noah Kim"]
    turns = []
    for f, q, heard in c.turns:
        t = getattr(c.truth, f)
        turns.append({"label": LABEL[f], "q": q, "heard": heard, "got": fmt(f, careful[f]), "truth": fmt(f, t),
                      "ok": careful[f] == t, "fixed": fixed[f] == t})
    data = {"turns": turns, "patient": names[k % len(names)], "payor": "Prairie Valley Health",
            "service": SERVICE.get(c.specialty, c.specialty), "readback": False,
            "est": money(estimate(careful, 150, 12)), "est_rb": money(estimate(fixed, 150, 12)),
            "est_truth": money(estimate(c.truth, 150, 12))}
    from app.widgets.benefitcard import benefit_card

    benefit_card(data, key=f"bc_{k}")
    log("benefit_call", {"call": k})
    bv = (asset_json("care_readiness.json") or {}).get("benefits", {})
    if bv:
        st.markdown(f"Across 120 calls, careful parsing took the mean error in a 12-visit estimate from "
                    f"**\\${bv['naive']['estimate_abs_error_mean']:,.0f}** to **\\${bv['careful']['estimate_abs_error_mean']:,.0f}**; "
                    f"reading every number back took it to **\\${bv['careful_readback']['estimate_abs_error_mean']:,.0f}**.")
        with st.expander("How we know"):
            import pandas as pd

            lab = {"naive": "First number heard", "careful": "Careful parser", "careful_readback": "Careful parser + read-back"}
            st.dataframe(pd.DataFrame([{"Method": lab[a], "Fields right": v["field_accuracy"],
                                        "Wrong fields given confidently": v["fluent_wrong_fields"],
                                        "Calls fully right": f"{v['calls_fully_correct']} of {v['calls']}",
                                        "Mean estimate error": v["estimate_abs_error_mean"],
                                        "Estimates off by $100+": v["estimates_off_by_100_plus"]} for a, v in bv.items()]),
                         hide_index=True, width="stretch",
                         column_config={"Fields right": st.column_config.NumberColumn(format="percent"),
                                        "Mean estimate error": st.column_config.NumberColumn(format="dollar")})
            st.caption("120 synthetic calls. Reps spell numbers out, correct themselves, say 'remaining' instead of "
                       "'met', and quote what the plan pays instead of the member. Speech recognition swaps teens "
                       "and tens (fifteen heard as fifty) on a quarter of numbers. Read-back assumes the rep catches "
                       "90% of wrong values read to them; that rate is an assumption, not a measurement.")
elif pick == "Watch a status call":
    st.caption("The phone agent works an IVR for an authorization status, or you play the payor rep.")
    run_view(TOOLS[pick])
else:
    from app.widgets.benefits import cost_calculator

    st.caption("Move any term. Each bar is one visit, split into what the patient and the plan pay, using the same "
               "rules as the estimator above.")
    cost_calculator()
