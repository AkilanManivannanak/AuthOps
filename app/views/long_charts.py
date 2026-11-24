import pandas as pd
import streamlit as st

from app.ui import asset_json, log, setup, tiles
from authops.docagent.longdoc import RULES, make_chart
from authops.docagent.validators import offline_agent, offline_oneshot

setup("Long-chart validation", "Check a 12 to 150 page chart against payor rules, one model call vs a background agent.")

m = asset_json("care_readiness.json") or {}
da = m.get("docagent", {})
arms = [a for a in ("claude_oneshot", "claude_agent", "offline_oneshot", "offline_agent") if a in da]
LABEL = {"claude_oneshot": "Claude, one call", "claude_agent": "Claude, background agent",
         "offline_oneshot": "Offline single pass", "offline_agent": "Offline document finder"}

if "claude_agent" not in da:
    st.info("The Claude arms are not in this build yet. They run on the owner's machine with "
            "`python scripts/run_care_readiness.py --llm`. The offline arms below are deterministic stand-ins: "
            "they show the harness works, not how a model performs.")

if da:
    best = "claude_agent" if "claude_agent" in da else "offline_agent"
    base = "claude_oneshot" if "claude_oneshot" in da else "offline_oneshot"
    tiles([
        (m.get("docagent_corpus", {}).get("charts", 0), "synthetic charts, 12 to 150 pages", "int", False),
        (da[base]["summary"]["all"]["false_pass"], f"rules waved through wrongly: {LABEL[base].lower()}", "int", True),
        (da[best]["summary"]["all"]["false_pass"], f"rules waved through wrongly: {LABEL[best].lower()}", "int", False),
        (da[best]["summary"]["all"]["accuracy"], f"accuracy on decided rules: {LABEL[best].lower()}", "pct", False),
    ])
    rows = []
    for a in arms:
        for g in ("all", "1-40 pages", "41-100 pages", "100+ pages", "cross_page", "medical_necessity"):
            s = da[a]["summary"].get(g)
            if s:
                rows.append({"arm": LABEL[a], "slice": g, "accuracy": s["accuracy"], "coverage": s["coverage"],
                             "caught failing rules": s["catch_rate"], "false passes": s["false_pass"],
                             "false blocks": s["false_block"]})
    st.markdown("### Results by chart length and rule type")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    cost = pd.DataFrame([{"arm": LABEL[a], "p50 seconds per chart": da[a]["p50_seconds"],
                          "cost per chart (USD)": da[a]["cost_per_chart_usd"], "mean turns": da[a]["mean_turns"],
                          "charts fully correct": f"{da[a]['charts_fully_correct']}/{da[a]['charts']}"} for a in arms])
    st.markdown("### Latency and cost per chart")
    st.dataframe(cost, hide_index=True, width="stretch")
    st.caption("A false pass is the expensive error: the request goes out, the payor denies it, and care waits. "
               "Coverage below 100% means the arm sent a rule to a person instead of guessing, which costs minutes, "
               "not a denial.")

st.markdown("### Try a chart yourself")
c1, c2, c3 = st.columns([1, 1, 2])
n_pages = c1.select_slider("Chart length (pages)", [12, 30, 60, 100, 150], value=100)
idx = c2.number_input("Chart number", 0, 500, 7)
chart = make_chart(int(idx), n_pages, seed=97)
results = [offline_oneshot(chart), offline_agent(chart)]
log("long_chart", {"pages": n_pages, "idx": int(idx)})
from app.widgets.chartread import chart_read  # noqa: E402

rules = [{"name": k.split("_", 1)[1].replace("_", " "), "text": t, "truth": bool(chart.truth[k]),
          "key": list(chart.key_pages[k]),
          "arms": [{"v": r.findings[k].verdict, "p": list(r.findings[k].pages)} for r in results]}
         for k, t in RULES.items()]
c3.caption(f"Rules this chart fails: {', '.join(k for k, v in chart.truth.items() if not v) or 'none'}. "
           "Click a rule to light the pages that decide it; click any page to read it.")
chart_read(chart.pages, sorted(chart.handwritten), chart.specialty.replace("_", " "),
           [LABEL[r.arm] for r in results], rules, key=f"cr_{n_pages}_{int(idx)}")

with st.expander("How the charts are built and scored"):
    st.markdown(
        "- Each chart is a request cover page plus a diagnostic evaluation, a standardized assessment, a treatment "
        "plan (and for PT a conservative-care history), buried among daily session notes.\n"
        "- Distractors repeat the same kind of fact with the wrong value: a signed consent form, an assessment from "
        "a prior episode, a ruled-out diagnosis, an early hours figure.\n"
        "- Each of the 8 rules fails on about 30% of charts, and the answer key is known.\n"
        "- Every verdict must cite a page and an exact quote. A quote that is not on the cited page turns the "
        "verdict into needs-human, so a confident answer without evidence never counts as a pass.\n"
        "- The Claude agent gets three tools: keyword search over the chart, read up to 3 pages, and record a "
        "finding. It runs asynchronously, outside the request path.")
