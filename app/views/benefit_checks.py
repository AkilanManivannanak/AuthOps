import random

import streamlit as st

from app.ui import asset_json, log, run_view, setup, switch
from authops.benefits.calls import FIELDS, estimate, extract_careful, make_calls, readback

from app.account import role as _role  # noqa: E402

setup("My costs" if _role() == "patient" else "Benefit checks",
      "Estimate your share of the cost before your visits." if _role() == "patient" else
      "One call to the payor becomes one accurate cost quote, saved to the patient.")

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
from app.account import role, save, today, ws  # noqa: E402
from authops import workspace as W  # noqa: E402

if role() == "patient":
    TOOLS = {"Cost calculator": "cost"}
    pick = "Cost calculator"
else:
    TOOLS = {"Phone benefit check": None, "Watch a status call": "app/views/phone_agent.py", "Cost calculator": "cost"}
    pick = switch(TOOLS, "bc")
if pick == "Phone benefit check":
    w = ws()
    ids = [p["id"] for p in w["patients"]]
    focus = st.session_state.get("focus") if st.session_state.get("focus") in ids else ids[0]
    c1, c2 = st.columns([3, 1.2])
    pid = c1.selectbox("Check benefits for", ids, index=ids.index(focus),
                       format_func=lambda i: f"{W.find(w, i)['name']} · {W.find(w, i)['payor_name']}")
    st.session_state.focus = pid
    pt = W.find(w, pid)
    k, c, careful, fixed = calls[pt["seed"] % len(calls)]
    names = [pt["name"]] * 6
    turns = []
    for f, q, heard in c.turns:
        t = getattr(c.truth, f)
        turns.append({"label": LABEL[f], "q": q, "heard": heard, "got": fmt(f, careful[f]), "truth": fmt(f, t),
                      "ok": careful[f] == t, "fixed": fixed[f] == t})
    data = {"turns": turns, "patient": names[k % len(names)], "payor": pt["payor_name"],
            "service": SERVICE.get(c.specialty, c.specialty), "readback": False,
            "est": money(estimate(careful, 150, 12)), "est_rb": money(estimate(fixed, 150, 12)),
            "est_truth": money(estimate(c.truth, 150, 12))}
    from app.widgets.benefitcard import benefit_card

    benefit_card(data, key=f"bc_{k}_{pid}")
    log("benefit_call", {"call": k})
    if pt.get("benefit"):
        c2.markdown(f"<div class='ao-muted' style='margin-top:1.9rem'>Saved {pt['benefit']['on']}: {pt['benefit']['estimate']} for 12 visits</div>",
                    unsafe_allow_html=True)
    elif c2.button("Save to their record", type="primary", width="stretch"):
        pt["benefit"] = {"estimate": data["est_rb"], "on": f"{today():%b %d}"}
        W.activity(w, f"Checked {pt['name']}'s benefits: {data['est_rb']} for the next 12 visits", "benefit_checks")
        save("Estimate saved to " + pt["name"] + ".")
        st.rerun()
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
            st.caption("120 sample calls. Reps spell numbers out, correct themselves, say 'remaining' instead of "
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
