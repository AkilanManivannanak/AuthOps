"""Sign-in page preview: a patient moving from a faxed plan to an approval, the way the app handles it."""
from __future__ import annotations

import streamlit as st

from app.widgets.theme import BASE_CSS

CSS = BASE_CSS + """
.stage{position:relative;margin-top:26px;height:360px;max-width:560px}
.glow{position:absolute;inset:30px 10px 10px 30px;border-radius:40px;filter:blur(38px);opacity:.55;
 background:radial-gradient(60% 60% at 30% 40%,#FFCDFF 0,transparent 70%),radial-gradient(50% 60% at 75% 60%,#FFB49D 0,transparent 70%)}
.win{position:absolute;left:0;top:0;width:86%;background:#fff;border:1px solid var(--sand);border-radius:22px;
 box-shadow:0 30px 60px -36px rgba(30,5,37,.45);padding:18px 18px 14px;transform:perspective(900px) rotateY(-6deg) rotateX(3deg);transform-origin:left}
.bar{display:flex;gap:6px;margin-bottom:12px}.bar i{width:8px;height:8px;border-radius:50%;background:#ECE5D8}
.hd{display:flex;justify-content:space-between;align-items:baseline}.hd b{font:400 18px Fraunces,Georgia,serif}.hd span{font-size:11px;color:var(--muted)}
.row{display:grid;grid-template-columns:34px 1fr auto;gap:10px;align-items:center;padding:10px 6px;border-top:1px solid #F3EDE6}
.av{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;color:#fff;font:600 12px 'DM Sans',system-ui,sans-serif}
.nm{font-weight:600;font-size:13px}.sv{font-size:11.5px;color:var(--muted)}
.pill{font:600 11px 'DM Sans',system-ui,sans-serif;border-radius:999px;padding:4px 10px;white-space:nowrap;transition:all .45s}
.track{display:flex;gap:4px;margin-top:6px}.track i{height:4px;flex:1;border-radius:4px;background:#F0EAE2;transition:background .45s}
.float{position:absolute;right:0;top:206px;width:58%;background:#fff;border:1px solid var(--sand);border-radius:18px;padding:14px 16px 14px 18px;
 box-shadow:0 26px 50px -30px rgba(30,5,37,.55);animation:bob 6s ease-in-out infinite}
.float:before{content:"";position:absolute;left:0;top:14px;bottom:14px;width:3px;border-radius:3px;background:var(--rose)}
.float .t{font:600 10px 'DM Sans',system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--rose)}
.float .m{font-size:13px;margin-top:4px;line-height:1.4}
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
.facts{display:flex;gap:26px;margin-top:8px;flex-wrap:nowrap}
.facts>div{flex:1;min-width:0}
.facts b{display:block;font:300 34px/1 Fraunces,Georgia,serif;color:var(--violet)}.facts span{font-size:12px;color:var(--muted)}
@media(max-width:700px){.stage{display:none}.facts{gap:18px}.facts b{font-size:28px}}
@media (prefers-reduced-motion:reduce){.float{animation:none}}
"""

JS = r"""
export default function(component){
 const {parentElement}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const S=[["Plan received","#F4F0EA","#6E5C76"],["Signature missing","#FBEAF1","#A8355F"],["Fixed, ready to send","#EFE7FA","#5B2A86"],
          ["Sent to payor","#FFF1EA","#B4532F"],["Approved · clear for care","#5B2A86","#fff"]];
 const P=[["Ava N.","Physical therapy · Northwind","#E0855F",0],["Noah R.","ABA therapy · Keystone","#8C5FB9",2],["Ines O.","Behavioral health · Harborline","#32073E",3]];
 root.innerHTML=`<div class="stage"><div class="glow"></div><div class="win"><div class="bar"><i></i><i></i><i></i></div>
  <div class="hd"><b>Today</b><span>3 patients · updated just now</span></div>
  ${P.map((p,i)=>`<div class="row"><div class="av" style="background:${p[2]}">${p[0][0]}</div><div><div class="nm">${p[0]}</div><div class="sv">${p[1]}</div>
   <div class="track">${S.map(()=>"<i></i>").join("")}</div></div><span class="pill" id="p${i}"></span></div>`).join("")}</div>
  <div class="float"><div class="t">Action required</div><div class="m"><b>Keystone</b> now limits physical therapy to 20 visits. 2 requests held and fixed before sending.</div></div></div>
  <div class="facts"><div><b data-n="86" data-s="%">0</b><span>approved in full the first time</span></div>
  <div><b data-n="50">0</b><span>denials stopped before the payor</span></div><div><b data-n="3">0</b><span>ways in: family, clinic, operations</span></div></div>`;
 const st=P.map(p=>p[3]);
 function paint(){P.forEach((p,i)=>{const s=S[st[i]],el=root.querySelector("#p"+i);el.textContent=s[0];el.style.background=s[1];el.style.color=s[2];
  root.querySelectorAll(".row")[i].querySelectorAll(".track i").forEach((t,k)=>t.style.background=k<=st[i]?(st[i]===4?"#5B2A86":"#C9B3E6"):"#F0EAE2")})}
 paint();const reduce=matchMedia("(prefers-reduced-motion: reduce)").matches;
 const tick=setInterval(()=>{if(reduce)return;const i=Math.floor(Math.random()*P.length);st[i]=st[i]>=4?0:st[i]+1;paint()},1400);
 root.querySelectorAll(".facts b").forEach(b=>{const n=+b.dataset.n,s=b.dataset.s||"",t0=performance.now();
  const f=t=>{const k=Math.min(1,(t-t0)/1200);b.textContent=Math.round(n*(1-Math.pow(1-k,3)))+s;if(k<1)requestAnimationFrame(f)};requestAnimationFrame(f)});
 return ()=>clearInterval(tick);
}
"""

_component = st.components.v2.component("authops_preview", css=CSS, js=JS)


def preview(key: str = "preview") -> None:
    _component(data={}, key=key)
