"""Benefit check: the call plays as chat bubbles and fills a patient cost card. With read-back on, every
number is read back to the rep, who corrects what speech recognition got wrong."""
from __future__ import annotations

import streamlit as st

from app.widgets.theme import BASE_CSS

CSS = BASE_CSS + """
.top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px;flex-wrap:wrap}
.sw{display:inline-flex;align-items:center;gap:10px;cursor:pointer;font:600 13px 'DM Sans',system-ui,sans-serif;user-select:none}
.sw i{width:40px;height:22px;border-radius:99px;background:#E7DFE9;position:relative;transition:background .2s}
.sw i:after{content:"";position:absolute;left:3px;top:3px;width:16px;height:16px;border-radius:50%;background:#fff;transition:left .2s;box-shadow:0 1px 3px rgba(0,0,0,.2)}
.sw.on i{background:#5B2A86}.sw.on i:after{left:21px}
.wrap{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:18px}@media(max-width:900px){.wrap{grid-template-columns:1fr}}
.chat{padding:14px;height:560px;overflow:auto;display:flex;flex-direction:column;gap:8px}
.b{max-width:84%;padding:9px 12px;border-radius:14px;font-size:13px;line-height:1.4;animation:rise .3s ease both}
.b.q{align-self:flex-end;background:#1E0525;color:#fff;border-bottom-right-radius:4px}
.b.a{align-self:flex-start;background:var(--cream);border:1px solid var(--sand);border-bottom-left-radius:4px}
.b.rb{align-self:flex-end;background:#5B2A86;color:#fff;border-bottom-right-radius:4px}
.b .who{font:600 10px 'DM Sans',system-ui,sans-serif;letter-spacing:.1em;text-transform:uppercase;opacity:.6;display:block;margin-bottom:2px}
.cardc{padding:18px 20px}.cardc h4{margin:0 0 2px;font:400 22px Fraunces,Georgia,serif}.cardc .sub{color:var(--muted);font-size:12px;margin-bottom:10px}
.row{display:flex;justify-content:space-between;align-items:baseline;padding:7px 0;border-bottom:1px solid #F3EDE6;font-size:13px}
.row span{color:#6E5C76}.row b{font-weight:600;transition:color .3s;opacity:.18}.row b.on{opacity:1}
.row b.wrong{color:#C0446A}.row b.fixed{color:#5B2A86;animation:flip .5s ease}
.row small{font-size:11px;color:#C0446A;margin-left:6px}
@keyframes flip{0%{transform:rotateX(90deg)}100%{transform:none}}
.tot{margin-top:12px;padding:14px;border-radius:14px;background:linear-gradient(135deg,#FDF8F3,#FAE8E8);display:flex;justify-content:space-between;align-items:flex-end}
.tot b{font:400 34px/1 Fraunces,Georgia,serif;display:block}.tot span{font-size:12px;color:var(--muted)}
.truth{font-size:12px;color:var(--muted);text-align:right}
"""

JS = r"""
export default function(component){
 const {data,parentElement}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const D=data,T=D.turns;let rb=D.readback,timers=[];
 root.innerHTML=`<div class="top"><div class="eyebrow">Benefit check by phone · ${D.payor} · ${D.service}</div>
  <span class="sw ${rb?"on":""}" id="sw"><i></i>Read numbers back to the rep</span><button class="btn ghost" id="go">Replay the call</button></div>
  <div class="wrap"><div class="card chat" id="chat"></div><div class="card cardc"><h4>${D.patient}</h4><div class="sub">${D.payor} · ${D.service}</div>
  ${T.map((t,i)=>`<div class="row"><span>${t.label}</span><b id="v${i}">·</b></div>`).join("")}
  <div class="tot"><div><b id="tot">·</b><span>estimated cost for the next 12 visits</span></div><div class="truth" id="tr"></div></div></div></div>`;
 const chat=root.querySelector("#chat");
 const say=(cls,who,txt)=>{chat.insertAdjacentHTML("beforeend",`<div class="b ${cls}"><span class="who">${who}</span>${txt}</div>`);chat.scrollTop=chat.scrollHeight};
 function play(){timers.forEach(clearTimeout);timers=[];chat.innerHTML="";let t0=0;
  T.forEach((t,i)=>{const v=root.querySelector("#v"+i);v.className="";v.textContent="·";
   timers.push(setTimeout(()=>say("q","Agent",t.q),t0));t0+=450;
   timers.push(setTimeout(()=>{say("a","Payor rep",t.heard);v.className="on "+(t.ok?"":"wrong");v.innerHTML=t.got+(t.ok?"":` <small>truth ${t.truth}</small>`)},t0));t0+=500;
   if(rb&&!t.ok){timers.push(setTimeout(()=>say("rb","Agent, reading back",`Just to confirm, ${t.label.toLowerCase()} is ${t.got}?`),t0));t0+=600;
    if(t.fixed){timers.push(setTimeout(()=>{say("a","Payor rep",`No, it's ${t.truth}.`);v.className="on fixed";v.textContent=t.truth},t0));t0+=600}
    else{timers.push(setTimeout(()=>say("a","Payor rep","Yes, that's right."),t0));t0+=500}}});
  timers.push(setTimeout(()=>{const e=rb?D.est_rb:D.est;const tt=root.querySelector("#tot");tt.textContent=e;tt.style.color=e===D.est_truth?"#5B2A86":"#C0446A";
   root.querySelector("#tr").innerHTML=e===D.est_truth?"matches the plan":`plan says ${D.est_truth}`},t0+200))}
 root.querySelector("#go").onclick=play;
 root.querySelector("#sw").onclick=e=>{rb=!rb;e.currentTarget.classList.toggle("on",rb);play()};
 play();return ()=>timers.forEach(clearTimeout);
}
"""

_component = st.components.v2.component("authops_benefit_card", css=CSS, js=JS)


def benefit_card(data: dict, key: str) -> None:
    _component(data=data, key=key)
