"""Sign-in page showcase: three short stories that play on their own, one per kind of user, then three
measured numbers. Shown before anyone signs in, so it has to speak to everyone."""
from __future__ import annotations

import streamlit as st

from app.widgets.theme import BASE_CSS

CSS = BASE_CSS + """
.sc{margin-top:26px;max-width:560px}
.pills{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
.pills button{font:600 12.5px 'DM Sans',system-ui,sans-serif;border:1px solid var(--sand);background:#fff;color:#6E5C76;border-radius:999px;padding:7px 13px;cursor:pointer;position:relative;overflow:hidden}
.pills button.on{color:#fff;background:var(--ink);border-color:var(--ink)}
.pills button.on i{position:absolute;left:0;bottom:0;height:3px;background:#FFB49D;animation:fill 5.5s linear forwards}
@keyframes fill{from{width:0}to{width:100%}}
.stage{position:relative;height:290px;perspective:900px}
.doc{position:absolute;left:0;top:18px;width:46%;height:230px;background:#fff;border:1px solid var(--sand);border-radius:12px;padding:16px 14px;
 box-shadow:0 20px 40px -28px rgba(30,5,37,.45);transform:rotate(-4deg);transition:transform .6s}
.doc .ln{height:7px;border-radius:4px;background:#EEE8F1;margin:9px 0}
.doc .ln.s{width:55%}.doc .ln.m{width:80%}.doc .h{height:11px;width:62%;background:#D9CDE3;border-radius:4px;margin-bottom:14px}
.doc .scan{position:absolute;left:8px;right:8px;height:2px;background:linear-gradient(90deg,transparent,#8C5FB9,transparent);box-shadow:0 0 12px #8C5FB9;top:20px;animation:scan 1.6s ease-in-out 2}
@keyframes scan{0%{top:20px}50%{top:210px}100%{top:20px}}
.doc .hl{position:absolute;left:12px;height:13px;border:2px solid #8C5FB9;border-radius:4px;opacity:0;animation:hl .4s ease forwards}
@keyframes hl{to{opacity:1}}
.arrow{position:absolute;left:47%;top:120px;width:7%;height:2px;background:repeating-linear-gradient(90deg,#8C5FB9 0 6px,transparent 6px 11px);animation:dash 1s linear infinite}
@keyframes dash{to{background-position:22px 0}}
.res{position:absolute;right:0;top:0;width:50%;background:#fff;border:1px solid var(--sand);border-radius:16px;padding:16px 16px 14px;
 box-shadow:0 26px 50px -30px rgba(30,5,37,.55);opacity:0;transform:translateY(14px) rotateX(8deg);transition:all .55s cubic-bezier(.2,.8,.2,1)}
.res.show{opacity:1;transform:none}
.who{font:600 10px 'DM Sans',system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.stamp{display:inline-block;margin:8px 0 6px;transform:rotate(-3deg);border:3px solid;border-radius:9px;padding:2px 10px;font:900 14px 'DM Sans',system-ui,sans-serif;letter-spacing:.14em}
.r1{font:400 16px/1.3 Fraunces,Georgia,serif;margin:4px 0 8px}
.row{display:flex;justify-content:space-between;font-size:12px;padding:5px 0;border-top:1px solid #F3EDE6;opacity:0;animation:hl .35s ease forwards}
.row span{color:#6E5C76}.row b{font-weight:600}
.next{margin-top:10px;padding:8px 10px;border-radius:10px;background:linear-gradient(135deg,#FDF8F3,#FAE8E8);font-size:12px;opacity:0;animation:hl .35s ease forwards}
.next b{color:#5B2A86}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:8px}
.st{border-top:2px solid var(--sand);padding-top:10px}.st b{display:block;font:300 30px/1 Fraunces,Georgia,serif;color:var(--violet)}
.st span{font-size:12px;color:#6E5C76;line-height:1.35;display:block;margin-top:6px}
.fine{font-size:11px;color:var(--muted);margin-top:10px}
@media(max-width:520px){.stage{height:400px}.doc{width:52%}.res{width:56%}}
"""

JS = r"""
export default function(component){
 const {data,parentElement}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const S=[
  {tab:"For patients and families",who:"Your insurance letter",stamp:["DENIED","#C0446A"],head:"Explained in plain English, with your deadline.",
   rows:[["Reason","Too many visits asked"],["Appeal by","Dec 24"],["Can you appeal?","Yes"]],next:"Ask the clinic to appeal with your doctor's note."},
  {tab:"For clinic teams",who:"Treatment plan, before sending",stamp:["1 TO FIX","#B4532F"],head:"Fixed before the payor ever sees it.",
   rows:[["Signature","Missing"],["Codes","ICD-10 and CPT valid"],["Approval odds","2% → 84% at 15 visits"]],next:"Get the provider's signature, then send."},
  {tab:"For operations",who:"Payor decisions this week",stamp:["NEW RULE","#5B2A86"],head:"A payor changed its limits. Caught in a week.",
   rows:[["Payor","Keystone"],["New limit","20 PT visits"],["Requests held","3 before denial"]],next:"Approve the rule so every new request is checked."}];
 let i=0,timer=null;
 root.innerHTML=`<div class="sc"><div class="pills">${S.map((s,k)=>`<button data-k="${k}">${s.tab}<i></i></button>`).join("")}</div>
  <div class="stage"><div class="doc" id="doc"></div><div class="arrow"></div><div class="res" id="res"></div></div>
  <div class="stats">${data.stats.map(s=>`<div class="st"><b>${s[0]}</b><span>${s[1]}</span></div>`).join("")}</div>
  <div class="fine">Measured on AuthOps' test set of letters, plans and payor decisions.</div></div>`;
 const doc=root.querySelector("#doc"),res=root.querySelector("#res");
 function show(k){i=k;const s=S[k];clearTimeout(timer);
  root.querySelectorAll(".pills button").forEach((b,j)=>{b.classList.toggle("on",j===k);const n=b.querySelector("i");n.style.animation="none";n.offsetWidth;n.style.animation=""});
  doc.innerHTML=`<div class="h"></div>${[1,0,1,2,0,1,2,1].map(c=>`<div class="ln ${["","s","m"][c]}"></div>`).join("")}<div class="scan"></div>`;
  res.classList.remove("show");res.innerHTML="";
  [48,102,150].forEach((y,n)=>setTimeout(()=>{const h=document.createElement("div");h.className="hl";h.style.top=y+"px";h.style.width=(60-n*12)+"%";doc.appendChild(h)},500+n*450));
  setTimeout(()=>{res.innerHTML=`<div class="who">${s.who}</div><div class="stamp" style="color:${s.stamp[1]};border-color:${s.stamp[1]}">${s.stamp[0]}</div>
    <div class="r1">${s.head}</div>${s.rows.map((r,n)=>`<div class="row" style="animation-delay:${200+n*180}ms"><span>${r[0]}</span><b>${r[1]}</b></div>`).join("")}
    <div class="next" style="animation-delay:900ms"><b>Next:</b> ${s.next}</div>`;res.classList.add("show")},1900);
  timer=setTimeout(()=>show((k+1)%S.length),5500)}
 root.querySelectorAll(".pills button").forEach(b=>b.onclick=()=>show(+b.dataset.k));
 show(0);return ()=>clearTimeout(timer);
}
"""

_component = st.components.v2.component("authops_showcase", css=CSS, js=JS)


def showcase(stats: list[tuple[str, str]]) -> None:
    _component(data={"stats": stats}, key="showcase")
