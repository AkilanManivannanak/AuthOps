import json
import time

import pandas as pd
import streamlit as st

from app.sandbox import browser_available, sandbox, start_agent_run
from app.ui import ASSETS, Timer, log, pill, require_tester, setup, store
from app.widgets.replay import TOOL_ICON, player  # noqa: F401

setup("Agent Theater", "Run the browser agent on a test portal. Turn up the chaos and watch it recover.")
t = require_tester("so your runs and diagnosis count")

PORTALS = {"northwind": "Northwind (commercial): survey pop-ups",
           "keystone": "Keystone (Medicaid MCO): iframe, calendar widget, masked ID, delayed notice",
           "summit": "Summit (federal): TOTP, session kicks, 503s, stale credential, wizard"}




tab_live, tab_replay = st.tabs(["Run it live", "Recorded runs"])

with tab_replay:
    folders = sorted((ASSETS / "replays").glob("*/run.json"))
    if not folders:
        st.warning("No recorded runs. Run scripts/build_app_assets.py.")
    else:
        names = {f.parent.name: json.loads(f.read_text()) for f in folders}
        pick = st.radio("Recorded run", list(names), horizontal=True, format_func=lambda n: n.replace("_", " "))
        run = names[pick]
        k = "ok" if run["status"] == "submitted" else "bad"
        st.markdown(f"{pill(run['status'], k)} &nbsp; portal **{run['portal']}** · {len(run['steps'])} steps · "
                    f"smoothness **{run['smoothness']}** · {run['duration_s']}s · guard {'on' if run['guard'] else 'off'}"
                    f" · {run.get('note', '')}", unsafe_allow_html=True)
        player(run, ASSETS / "replays" / pick)
        if pick == "keystone_guard_off_failure":
            st.markdown("#### Diagnose it")
            ans = st.radio("Why did this run fail?", [
                "The Medicaid ID was typed in the wrong format",
                "A session notice popped up over the form and nothing cleared it, so the next click could not land",
                "The credential was locked by the portal",
                "The calendar widget has a bug in the portal"], index=None)
            if ans and st.button("Check my diagnosis"):
                right = ans.startswith("A session notice")
                log("diagnosis", {"answer": ans, "right": right})
                if right:
                    st.success("Correct. The pick_date call timed out because the notice covered the field. "
                               "With the overlay guard on, the runtime closes it before acting (compare the "
                               "keystone_aba_iframe_calendar replay).")
                    if t:
                        store().task(tester_id=t["id"], task="agent_diagnosis", success=1,
                                     seconds=Timer("diag").seconds, detail=ans)
                else:
                    st.error("Not quite. Look at what is on screen at the step that failed.")

with tab_live:
    if not browser_available():
        st.warning("No browser is available on this server, so live runs are off here. The recorded runs tab shows "
                   "real runs captured with the same code. Locally: `python -m playwright install chromium`.")
        st.stop()
    sb = sandbox()
    c1, c2 = st.columns([1.2, 1])
    with c1:
        portal = st.selectbox("Portal", list(PORTALS), format_func=PORTALS.get)
        cases = sb["cases"]
        idx = st.selectbox("Patient case", range(len(cases)),
                           format_func=lambda i: f"{cases[i]['case_id']} · {cases[i]['patient']['first_name']} "
                                                 f"{cases[i]['patient']['last_name']} · {cases[i]['specialty'].replace('_', ' ')}")
    with c2:
        st.markdown("**Chaos**")
        popup = st.slider("Survey pop-up rate (Northwind)", 0.0, 1.0, 0.35, 0.05)
        err503 = st.slider("503 rate on submit (Summit)", 0.0, 0.8, 0.15, 0.05)
        kick = st.slider("Session kick rate (Summit)", 0.0, 0.5, 0.08, 0.02)
        st.markdown("**Safety controls**")
        guard = st.toggle("Overlay guard", value=True)
        thr = st.select_slider("Disable a credential after N failed logins", [2, 3, 99], value=2,
                               format_func=lambda v: "never" if v == 99 else str(v))
    if st.button("Run the agent", type="primary", width="stretch"):
        log("agent_run_start", {"portal": portal, "popup": popup, "503": err503, "kick": kick, "guard": guard, "thr": thr})
        q, th = start_agent_run(cases[idx], portal, {"survey_modal_rate": popup, "summit_503_rate": err503,
                                                     "summit_kick_rate": kick}, guard, thr, wall_clock_s=45)
        shot_box, steps_box = st.columns([1.6, 1])
        img_ph, rows, result = shot_box.empty(), [], None
        tl_ph = steps_box.empty()
        t0 = time.time()
        while True:
            kind, a, b = q.get(timeout=120)
            if kind == "step":
                rows.append(a)
                if b:
                    img_ph.image(b, caption=f"step {a['idx']}: {a['tool']}", width="stretch")
                tl_ph.markdown("\n".join(
                    f"- {'✅' if s['ok'] else '❌'} {TOOL_ICON.get(s['tool'], '•')} **{s['tool']}** "
                    f"<span class='ao-muted'>{s['error_class'] or s['detail'][:60]}</span>" for s in rows[-14:]),
                    unsafe_allow_html=True)
            elif kind == "done":
                result = a
                break
            else:
                st.error(f"The browser could not start on this server ({a}). The Recorded runs tab shows real runs "
                         "captured with the same code.")
                break
        if result:
            ok = result["status"] == "submitted"
            st.markdown(f"### {pill(result['status'], 'ok' if ok else 'bad')} &nbsp; {result['note']}", unsafe_allow_html=True)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Steps", result["steps"])
            m2.metric("Smoothness", result["smoothness"])
            m3.metric("Seconds", result["duration_s"])
            m4.metric("Verified confirmation", "yes" if result["verified"] else "no")
            st.caption(f"Guard and recovery events: {result['counts'] or 'none'} · portal lockouts so far: "
                       f"{result['lockouts_total']}")
            st.dataframe(pd.DataFrame(result["credentials"]).rename(columns=lambda c: c.replace("_", " ").capitalize()), hide_index=True, width="stretch")
            if t:
                store().agent_run(tester_id=t["id"], portal=portal, case_id=cases[idx]["case_id"],
                                  status=result["status"], error_class=result["error_class"], steps=result["steps"],
                                  smoothness=result["smoothness"],
                                  settings=json.dumps({"popup": popup, "503": err503, "kick": kick, "guard": guard,
                                                       "thr": thr}))
            log("agent_run_done", {**{k: result[k] for k in ("status", "error_class", "steps", "smoothness")},
                                   "seconds": round(time.time() - t0, 1)})
