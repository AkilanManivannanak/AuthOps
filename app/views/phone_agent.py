import json
import random

import streamlit as st

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
tab_watch, tab_play, tab_norm, tab_stream = st.tabs(["Watch a call", "You are the payor rep", "Speech normalization", "Streaming"])

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
    .b.on{{opacity:1;transform:none}} .heard{{background:#F7F0EC;align-self:flex-start}} .said{{background:{FOREST};color:#FDF8F3;align-self:flex-end}}
    .dtmf{{align-self:flex-end;background:#1E0525;color:#FDF8F3;font-family:monospace}} .who{{font-size:.7rem;opacity:.7;margin-bottom:2px}}</style>
    <div class="c" id="c"></div><script>const B={json.dumps(bubbles)};const c=document.getElementById('c');
    B.forEach((b,i)=>{{const d=document.createElement('div');d.className='b '+b.k;
      d.innerHTML='<div class="who">'+(b.k==='heard'?'payor line':b.k==='dtmf'?'keypad (silent)':'agent')+'</div>'+(b.k==='dtmf'?'pressed '+b.t:b.t);
      c.appendChild(d);setTimeout(()=>d.classList.add('on'),i*650);}});</script>"""
    st.iframe(html, height=90 * len(bubbles) + 40)
    ans = res.answer if isinstance(res.answer, dict) else {}
    parts = [f"{k.replace('_', ' ')}: {v}" for k, v in ans.items()] if ans else ([str(res.answer)] if res.answer else [])
    st.markdown(f"**{res.status.replace('_', ' ').capitalize()}** after {res.turns} turns"
                + (f" · {' · '.join(parts)}" if parts else ""))

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


with tab_stream:
    import altair as alt
    import pandas as pd

    from authops.phone.stream import Budget, Playback, latency_report, speakable_chunks

    reply = normalize_for_speech(
        f"Thanks for holding. The member ID is {cases[0]['patient']['member_id']}, and the date of birth is "
        f"{cases[0]['patient']['dob']}. I'm calling to check the status of a prior authorization. "
        "Could you tell me if it has been approved?")
    chunks = speakable_chunks(reply)
    left, right = st.columns([1.1, 1])
    with left:
        st.markdown("**Chunks sent to speech as they arrive**")
        cut = st.slider("Rep talks over the agent after chunk", 1, len(chunks), len(chunks))
        pb = Playback()
        pb.say(reply)
        for _ in range(cut):
            pb.mark()
        if cut < len(chunks):
            pb.interrupt()
        for i, ch in enumerate(chunks):
            heard = i < cut
            st.markdown(f"<div class='ao-card' style='opacity:{1 if heard else .35}'>"
                        f"<span class='ao-pill' style='background:{'#EFE7FA' if heard else '#FBEAF1'};"
                        f"color:{'#5B2A86' if heard else '#A8355F'}'>{'heard' if heard else 'dropped'}</span> {ch}</div>",
                        unsafe_allow_html=True)
    with right:
        st.markdown("**Time to first audio**")
        llm_rate = st.slider("Model speed (tokens/s)", 20, 120, 60, 10)
        rep = latency_report([reply], Budget(llm_tokens_per_s=llm_rate))
        df = pd.DataFrame([{"mode": m, "stat": k, "ms": rep[m][k]} for m in ("full_response", "streaming")
                           for k in ("p50_ms", "p95_ms")])
        st.altair_chart(alt.Chart(df).mark_bar(cornerRadius=4).encode(
            x=alt.X("ms:Q", title="ms"), y=alt.Y("mode:N", title=None), color=alt.Color(
                "stat:N", scale=alt.Scale(range=["#8C5FB9", "#E0855F"]), legend=alt.Legend(orient="top", title=None)),
            yOffset="stat:N").properties(height=180), width="stretch")
        st.caption("Simulated from stated stage timings (speech-to-text, model first token, token rate, "
                   "text-to-speech first byte), not measured on a vendor.")
