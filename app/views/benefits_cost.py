import pandas as pd
import streamlit as st

from app.ui import asset_json, log, setup, tiles
from authops.benefits.calls import estimate, extract_careful, extract_naive, make_calls

setup("Benefits and cost",
      "For ABA, a phone call is often the only accurate source of plan details, and Silna's phone-agent post warns "
      "that a fluent wrong answer delays care. This page scores three ways of turning a rep's answers into plan "
      "fields, and shows what each mistake does to the patient's cost estimate.")

m = asset_json("care_readiness.json") or {}
bv = m.get("benefits", {})
LABEL = {"naive": "First number heard", "careful": "Careful parser", "careful_readback": "Careful + read-back"}
if bv:
    tiles([
        (bv["naive"]["field_accuracy"], "fields right, first number heard", "pct", True),
        (bv["careful_readback"]["field_accuracy"], "fields right, careful parser with read-back", "pct", False),
        (bv["naive"]["estimate_abs_error_mean"], "mean $ error in the 12-visit estimate (first number)", "int", True),
        (bv["careful_readback"]["estimate_abs_error_mean"], "mean $ error with read-back", "int", False),
    ])
    st.dataframe(pd.DataFrame([{"method": LABEL[a], "field accuracy": v["field_accuracy"],
                                "wrong fields given confidently": v["fluent_wrong_fields"],
                                "calls fully right": f"{v['calls_fully_correct']}/{v['calls']}",
                                "estimates off by $100+": v["estimates_off_by_100_plus"]} for a, v in bv.items()]),
                 hide_index=True, use_container_width=True)
    pf = pd.DataFrame({LABEL[a]: v["per_field"] for a, v in bv.items()})
    st.markdown("### Accuracy by field")
    st.dataframe(pf, use_container_width=True)
    st.caption("120 synthetic calls. Reps spell numbers out, correct themselves, answer with 'remaining' instead "
               "of 'met', say what the plan pays instead of what the member pays, and carve behavioral health out "
               "to another vendor. Speech recognition swaps teens and tens (fifteen heard as fifty) on a quarter of "
               "numbers. Read-back assumes the rep catches 90% of wrong values read to them; that rate is an "
               "assumption, not a measurement.")

st.markdown("### Listen to a call")
calls = make_calls(n=120)
i = st.slider("Call", 0, len(calls) - 1, 3)
call = calls[i]
naive, careful = extract_naive(call), extract_careful(call)
log("bv_call", {"i": i})
rows = []
for f, q, heard in call.turns:
    t = getattr(call.truth, f)
    rows.append({"field": f, "rep said (as heard)": heard, "truth": str(t),
                 "first number": f"{naive[f]} {'✓' if naive[f] == t else '✗'}",
                 "careful": f"{careful[f]} {'✓' if careful[f] == t else '✗'}"})
st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, height=460)
e_t, e_n, e_c = (estimate(x, 150, 12) for x in (call.truth, naive, careful))
c1, c2, c3 = st.columns(3)
c1.metric("True 12-visit cost", f"${e_t['patient_total']}" if e_t["patient_total"] is not None else "carve-out")
c2.metric("Quoted from first number", f"${e_n['patient_total']}" if e_n["patient_total"] is not None else "carve-out")
c3.metric("Quoted from careful parser", f"${e_c['patient_total']}" if e_c["patient_total"] is not None else "carve-out")

st.markdown("### Patient cost calculator")
with st.form("est"):
    a, b, c, d = st.columns(4)
    vals = dict(deductible=a.number_input("Deductible", 0, 20000, 1500), deductible_met=b.number_input("Deductible met", 0, 20000, 500),
                coinsurance_pct=c.number_input("Coinsurance %", 0, 100, 20), copay=d.number_input("Copay per visit", 0, 500, 0),
                oop_max=a.number_input("Out-of-pocket max", 0, 50000, 5000), oop_met=b.number_input("OOP met", 0, 50000, 800),
                visit_limit=c.number_input("Visit limit (0 = none)", 0, 400, 30) or None,
                visits_used=d.number_input("Visits used", 0, 400, 12))
    allowed = a.number_input("Allowed amount per visit", 1.0, 5000.0, 150.0)
    visits = b.number_input("Planned visits", 1, 520, 24)
    if st.form_submit_button("Estimate"):
        r = estimate(vals | {"plan_active": True, "in_network": True, "carve_out_vendor": None}, allowed, int(visits))
        st.success(f"Patient responsibility: ${r['patient_total']:,.2f}" + (f" · {r['note']}" if r["note"] else ""))
        log("estimate", {"visits": int(visits)})
