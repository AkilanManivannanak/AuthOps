
import pandas as pd
import streamlit as st
import yaml

from app.sandbox import browser_available, sandbox, start_agent_run
from app.ui import log, pill, setup
from authops.agent.policy import PLAYBOOK_DIR

setup("Playbook Studio",
      "Every portal has a plain-English playbook for people and the model, and a structured plan the agent "
      "executes. Edit the plan, backtest it on the sandbox, and see whether your change helps or breaks it.")

portal = st.radio("Portal", ["northwind", "keystone", "summit"], horizontal=True)
md = (PLAYBOOK_DIR / f"{portal}.md").read_text()
yml = (PLAYBOOK_DIR / f"{portal}.yaml").read_text()
a, b = st.columns(2)
with a:
    st.markdown("#### Plain-English playbook")
    st.markdown(md)
with b:
    st.markdown("#### Executable plan (edit me)")
    edited = st.text_area("plan", yml, height=520, label_visibility="collapsed", key=f"yml_{portal}")
    st.caption("Ideas: delete the `wait` step on Keystone, change a field label, drop the attestation on Summit.")

try:
    spec = yaml.safe_load(edited)
    assert isinstance(spec, dict) and "pages" in spec
    valid = True
except Exception as e:
    st.error(f"The plan is not valid YAML: {e}")
    valid = False

n = st.slider("Backtest on how many sandbox cases", 1, 5, 2)
if st.button("Backtest this plan", type="primary", disabled=not (valid and browser_available())):
    log("backtest", {"portal": portal, "edited": edited != yml, "n": n})
    rows = []
    prog = st.progress(0.0)
    for k, case in enumerate(sandbox()["cases"][:n]):
        q, _ = start_agent_run(case, portal, {"survey_modal_rate": 0.35, "summit_503_rate": 0.0,
                                              "summit_kick_rate": 0.0}, True, 2, spec=spec, wall_clock_s=40)
        while True:
            kind, res, _ = q.get(timeout=120)
            if kind in ("done", "error"):
                break
        if kind == "error":
            rows.append({"case": case["case_id"], "status": "error", "error": str(res)[:80]})
        else:
            rows.append({"case": case["case_id"], "status": res["status"], "error": res["error_class"],
                         "steps": res["steps"], "smoothness": res["smoothness"], "note": res["note"][:80]})
        prog.progress((k + 1) / n)
    df = pd.DataFrame(rows)
    ok = (df.status == "submitted").mean()
    st.markdown(f"### {pill(f'{ok:.0%} submitted', 'ok' if ok == 1 else 'bad')}", unsafe_allow_html=True)
    st.dataframe(df, hide_index=True, use_container_width=True)
    if edited != yml and ok < 1:
        st.info("Your edit broke something. Real AI Ops work is exactly this loop: change, backtest in a sandbox, "
                "ship only what holds. Revert by switching portals and back.")
elif not browser_available():
    st.caption("Backtests need a browser on the server; see Agent Theater for recorded runs.")
