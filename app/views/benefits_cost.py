import pandas as pd
import streamlit as st

from app.ui import asset_json, log, setup, tiles
from authops.benefits.calls import estimate, extract_careful, extract_naive, make_calls

setup("Benefits and cost", "Turn a payor call into plan fields and a patient cost estimate.")

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
                 hide_index=True, width="stretch")
    pf = pd.DataFrame({LABEL[a]: v["per_field"] for a, v in bv.items()})
    st.markdown("### Accuracy by field")
    st.dataframe(pf, width="stretch")
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
from app.widgets.benefits import call_player, cost_calculator  # noqa: E402

turns = [{"field": f, "q": q, "heard": heard, "truth": str(getattr(call.truth, f)), "naive": str(naive[f]),
          "careful": str(careful[f]), "n_ok": naive[f] == getattr(call.truth, f),
          "c_ok": careful[f] == getattr(call.truth, f)} for f, q, heard in call.turns]
e_t, e_n, e_c = (estimate(x, 150, 12) for x in (call.truth, naive, careful))
call_player(turns, [f"${e['patient_total']:,.2f}" if e["patient_total"] is not None else "carve-out" for e in (e_t, e_n, e_c)],
            key=f"call_{i}")

st.markdown("### Patient cost calculator")
st.caption("Move any term. Each bar is one visit, split into what the patient and the plan pay, using the same "
           "rules as the estimator the agent quotes from.")
cost_calculator()
