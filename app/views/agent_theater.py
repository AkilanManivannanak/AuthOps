import base64
import json
import time

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from app.sandbox import browser_available, sandbox, start_agent_run
from app.ui import ASSETS, FOREST, RED, Timer, log, pill, require_tester, setup, store

setup("Agent Theater",
      "A browser agent submits prior auths on three sandbox payor portals built with the failure modes real "
      "portals have. Turn the chaos up, switch the safety controls off, and watch what breaks.")
t = require_tester("so your runs and diagnosis count")

TOOL_ICON = {"goto": "🌐", "type_credential": "🔑", "enter_totp": "🔢", "click": "👆", "fill": "⌨️", "select": "🔽",
             "check": "☑️", "pick_date": "📅", "upload": "📎", "answer": "💬", "read_confirmation": "🧾",
             "dismiss_overlays": "🧹", "wait": "⏳", "swap_credential": "🔁", "backoff_resubmit": "↩️"}
PORTALS = {"northwind": "Northwind (commercial): survey pop-ups",
           "keystone": "Keystone (Medicaid MCO): iframe, calendar widget, masked ID, delayed notice",
           "summit": "Summit (federal): TOTP, session kicks, 503s, stale credential, wizard"}


def player(run: dict, folder) -> None:
    """Animated step player: screenshot + timeline, autoplay with scrubbing."""
    frames = []
    for s in run["steps"]:
        img = folder / s["image"] if s.get("image") else None
        b64 = base64.b64encode(img.read_bytes()).decode() if img and img.exists() else ""
        frames.append({"img": b64, "tool": s["tool"], "icon": TOOL_ICON.get(s["tool"], "•"), "ok": s["ok"],
                       "err": s.get("error_class", ""), "detail": s.get("detail", "")[:120], "kind": s.get("kind", "tool")})
    html = f"""
    <style>body{{margin:0;font-family:Inter,system-ui,sans-serif;color:#1F2A24}}
    .wrap{{display:grid;grid-template-columns:1.6fr 1fr;gap:14px}} .shot{{border:1px solid #E4E1D8;border-radius:14px;overflow:hidden;background:#fff}}
    .shot img{{width:100%;display:block}} .tl{{max-height:470px;overflow:auto;border:1px solid #E4E1D8;border-radius:14px;background:#fff;padding:6px}}
    .row{{display:flex;gap:8px;padding:6px 8px;border-radius:10px;font-size:.84rem;cursor:pointer;opacity:.35;transition:all .25s}}
    .row.seen{{opacity:1}} .row.cur{{background:#F1EEE6;box-shadow:inset 3px 0 0 {FOREST}}} .row.bad.seen{{color:{RED}}} .row.guard .t{{font-style:italic}}
    .ctl{{display:flex;gap:10px;align-items:center;margin-top:10px}} button{{border:0;border-radius:999px;padding:7px 16px;font-weight:700;background:#1F2A24;color:#FAF8F4;cursor:pointer}}
    input[type=range]{{flex:1;accent-color:{FOREST}}} .cap{{font-size:.8rem;color:#6C6C6C}}</style>
    <div class="wrap"><div class="shot"><img id="img"/></div><div class="tl" id="tl"></div></div>
    <div class="ctl"><button id="pp">Pause</button><input id="sl" type="range" min="0" max="{len(frames) - 1}" value="0"/>
    <span class="cap" id="cap"></span></div>
    <script>
    const F={json.dumps(frames)}; let i=0, playing=true;
    const tl=document.getElementById('tl'), img=document.getElementById('img'), sl=document.getElementById('sl'), cap=document.getElementById('cap');
    F.forEach((f,k)=>{{const d=document.createElement('div'); d.className='row'+(f.ok?'':' bad')+(f.kind==='guard'?' guard':'');
      d.innerHTML=`<span>${{f.icon}}</span><div><div class="t"><b>${{k+1}}. ${{f.tool}}</b> ${{f.ok?'':'· '+f.err}}</div><div class="cap">${{f.detail}}</div></div>`;
      d.onclick=()=>{{i=k;show();}}; tl.appendChild(d);}});
    function show(){{ const f=F[i]; if(f.img) img.src='data:image/jpeg;base64,'+f.img; sl.value=i;
      [...tl.children].forEach((r,k)=>{{r.classList.toggle('seen',k<=i); r.classList.toggle('cur',k===i);}});
      tl.children[i].scrollIntoView({{block:'nearest'}}); cap.textContent=`step ${{i+1}} of ${{F.length}}`; }}
    sl.oninput=()=>{{i=+sl.value; show();}}; document.getElementById('pp').onclick=e=>{{playing=!playing; e.target.textContent=playing?'Pause':'Play';}};
    setInterval(()=>{{ if(playing && i<F.length-1){{i++; show();}} }}, 900); show();
    </script>"""
    components.html(html, height=540)


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
            st.dataframe(pd.DataFrame(result["credentials"]), hide_index=True, width="stretch")
            if t:
                store().agent_run(tester_id=t["id"], portal=portal, case_id=cases[idx]["case_id"],
                                  status=result["status"], error_class=result["error_class"], steps=result["steps"],
                                  smoothness=result["smoothness"],
                                  settings=json.dumps({"popup": popup, "503": err503, "kick": kick, "guard": guard,
                                                       "thr": thr}))
            log("agent_run_done", {**{k: result[k] for k in ("status", "error_class", "steps", "smoothness")},
                                   "seconds": round(time.time() - t0, 1)})
