import json
import random

import streamlit as st
import streamlit.components.v1 as components

from app.ui import FOREST, log, setup
from authops.phone.ivr import PhoneAgent, correct_asr, normalize_for_speech, run_call
from authops.synth.generate import generate_cases

setup("Phone Agent", "Watch the phone agent work an IVR, or play the payor rep yourself.")


@st.cache_data
def phone_cases():
    cs = [c.model_dump(mode="json") for c in generate_cases(60, seed=12)]
    records = {c["patient"]["member_id"]: {"dob": c["patient"]["dob"], "status": random.Random(i).choice(
        ["approved", "pending", "denied"]), "ref": str(40000000 + i * 7919), "copay": random.Random(i).choice([0, 20, 25, 40])}
        for i, c in enumerate(cs)}
    return cs, records


cases, records = phone_cases()
tab_watch, tab_play, tab_norm = st.tabs(["Watch a call", "You are the payor rep", "Speech normalization"])

with tab_watch:
    a, b, c = st.columns([1.3, 1, 1])
    i = a.selectbox("Patient", range(len(cases)), format_func=lambda k: f"{cases[k]['patient']['first_name']} "
                    f"{cases[k]['patient']['last_name']} · {cases[k]['patient']['member_id']}")
    purpose = b.radio("Call purpose", ["status", "benefits"], horizontal=True)
    seed = c.number_input("Call seed", 0, 999, 1)
    res = run_call(cases[i], purpose, records, seed=int(seed))
    log("phone_call", {"purpose": purpose, "status": res.status, "turns": res.turns})
    bubbles = [{"k": e.kind, "t": e.text} for e in res.events]
    html = f"""<style>body{{margin:0;font-family:Inter,system-ui,sans-serif}} .c{{display:flex;flex-direction:column;gap:8px;max-width:760px}}
    .b{{padding:10px 14px;border-radius:16px;max-width:75%;opacity:0;transform:translateY(6px);transition:all .35s;font-size:.92rem;line-height:1.4}}
    .b.on{{opacity:1;transform:none}} .heard{{background:#F1EEE6;align-self:flex-start}} .said{{background:{FOREST};color:#FAF8F4;align-self:flex-end}}
    .dtmf{{align-self:flex-end;background:#1F2A24;color:#FAF8F4;font-family:monospace}} .who{{font-size:.7rem;opacity:.7;margin-bottom:2px}}</style>
    <div class="c" id="c"></div><script>const B={json.dumps(bubbles)};const c=document.getElementById('c');
    B.forEach((b,i)=>{{const d=document.createElement('div');d.className='b '+b.k;
      d.innerHTML='<div class="who">'+(b.k==='heard'?'payor line':b.k==='dtmf'?'keypad (silent)':'agent')+'</div>'+(b.k==='dtmf'?'pressed '+b.t:b.t);
      c.appendChild(d);setTimeout(()=>d.classList.add('on'),i*650);}});</script>"""
    components.html(html, height=90 * len(bubbles) + 40, scrolling=True)
    st.markdown(f"**Outcome:** {res.status} · extracted {res.answer} · {res.turns} turns")

with tab_play:
    st.caption("Type what a payor rep would say. The agent answers. Try asking for the member ID or date of birth, "
               "say something unclear, or mishear the carrier name as 'signal'.")
    if "call_case" not in st.session_state or st.button("New caller"):
        st.session_state.call_case = random.choice(cases)
        st.session_state.call_log = [("rep", "Thanks for calling provider services, this is Sam. How can I help?")]
    agent = PhoneAgent(st.session_state.call_case, "status")
    for who, text in st.session_state.call_log:
        with st.chat_message("assistant" if who == "agent" else "user", avatar="🤖" if who == "agent" else "🎧"):
            st.write(text)
    msg = st.chat_input("Say something as the rep")
    if msg:
        st.session_state.call_log.append(("rep", msg))
        heard = correct_asr(msg)
        said, dtmf = agent.decide(heard)
        reply = said or ("(presses " + dtmf + ")" if dtmf else
                         "Hi, I'm calling on behalf of the provider to check a prior authorization status.")
        if heard != msg:
            reply = f"[ASR corrected '{msg}' to '{heard}'] " + reply
        st.session_state.call_log.append(("agent", reply))
        log("rep_turn", {"msg": msg[:200]})
        st.rerun()

with tab_norm:
    txt = st.text_input("Text the agent is about to say", "Member PRV83557332 DOB 2012-02-07, rendering NPI 1234567893.")
    st.markdown("**What the text-to-speech engine receives:**")
    st.info(normalize_for_speech(txt))
    st.caption("IDs are read digit by digit, dates are spoken, and DOB and NPI are expanded, so a rep can type them "
               "correctly. A fluent wrong answer can delay a patient's care.")
