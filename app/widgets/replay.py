"""Recorded browser-agent run player."""
import base64
import json

import streamlit as st

from app.ui import FOREST, RED

TOOL_ICON = {"goto": "🌐", "type_credential": "🔑", "enter_totp": "🔢", "click": "👆", "fill": "⌨️", "select": "🔽",
             "check": "☑️", "pick_date": "📅", "upload": "📎", "answer": "💬", "read_confirmation": "🧾",
             "dismiss_overlays": "🧹", "wait": "⏳", "swap_credential": "🔁", "backoff_resubmit": "↩️"}

def player(run: dict, folder) -> None:
    """Animated step player: screenshot + timeline, autoplay with scrubbing."""
    frames = []
    for s in run["steps"]:
        img = folder / s["image"] if s.get("image") else None
        b64 = base64.b64encode(img.read_bytes()).decode() if img and img.exists() else ""
        frames.append({"img": b64, "tool": s["tool"], "icon": TOOL_ICON.get(s["tool"], "•"), "ok": s["ok"],
                       "err": s.get("error_class", ""), "detail": s.get("detail", "")[:120], "kind": s.get("kind", "tool")})
    html = f"""
    <style>body{{margin:0;font-family:Inter,system-ui,sans-serif;color:#1E0525}}
    .wrap{{display:grid;grid-template-columns:1.6fr 1fr;gap:14px}} .shot{{border:1px solid #ECE5D8;border-radius:14px;overflow:hidden;background:#fff}}
    .shot img{{width:100%;display:block}} .tl{{max-height:470px;overflow:auto;border:1px solid #ECE5D8;border-radius:14px;background:#fff;padding:6px}}
    .row{{display:flex;gap:8px;padding:6px 8px;border-radius:10px;font-size:.84rem;cursor:pointer;opacity:.35;transition:all .25s}}
    .row.seen{{opacity:1}} .row.cur{{background:#F7F0EC;box-shadow:inset 3px 0 0 {FOREST}}} .row.bad.seen{{color:{RED}}} .row.guard .t{{font-style:italic}}
    .ctl{{display:flex;gap:10px;align-items:center;margin-top:10px}} button{{border:0;border-radius:999px;padding:7px 16px;font-weight:700;background:#1E0525;color:#FDF8F3;cursor:pointer}}
    input[type=range]{{flex:1;accent-color:{FOREST}}} .cap{{font-size:.8rem;color:#7A6B80}}</style>
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
    st.iframe(html, height=540)
