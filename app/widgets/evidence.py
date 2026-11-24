"""Appeal evidence view: the chart as a strip of pages, a search sweep that lights the pages the
evidence is on, and a reader that opens any page with the quoted passage highlighted."""
from __future__ import annotations

import streamlit as st

from app.widgets.theme import BASE_CSS

CSS = BASE_CSS + """
.ev{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.25fr);gap:20px}
@media(max-width:900px){.ev{grid-template-columns:1fr}}
.stamp{display:inline-block;transform:rotate(-3deg);border:4px solid;border-radius:12px;padding:4px 16px;font:900 18px 'DM Sans',system-ui,sans-serif;letter-spacing:.16em;
 animation:land .35s cubic-bezier(.3,1.6,.5,1) both}
.reason{font:400 20px Fraunces,Georgia,serif;margin:12px 0 4px;line-height:1.3}
.cite{padding:12px 14px;margin-top:10px;cursor:pointer;transition:border-color .15s,transform .15s;animation:rise .3s ease both}
.cite:hover{transform:translateY(-1px);border-color:var(--lilac)}.cite q{font-style:italic;color:#3A2A40;display:block;margin-top:6px;line-height:1.45}
.ok{color:#5B2A86;background:#EFE7FA}.bad{color:#A8355F;background:#FBEAF1}
.strip{display:grid;grid-template-columns:repeat(auto-fill,minmax(18px,1fr));gap:4px;padding:12px;perspective:600px}
.pg{height:26px;border-radius:3px;background:#F7F1EC;border:1px solid var(--sand);cursor:pointer;position:relative;transition:transform .15s,background .3s,box-shadow .2s}
.pg:hover{transform:translateY(-3px) rotateX(12deg);box-shadow:0 6px 10px -6px rgba(30,5,37,.5)}
.pg.read{background:#EDE4F4}.pg.hit{background:#5B2A86;border-color:#5B2A86}.pg.sel{box-shadow:0 0 0 3px #FFB49D}
.pg.scan{background:#FFB49D}
.reader{padding:16px 18px;margin-top:12px;max-height:360px;overflow:auto;white-space:pre-wrap;font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;color:#3A2A40}
mark{background:#FFE3D8;color:#1E0525;border-radius:3px;padding:0 2px;box-shadow:0 0 0 2px #FFB49D}
.hdr{display:flex;justify-content:space-between;align-items:center;gap:10px}
"""

JS = r"""
export default function(component){
 const {data,parentElement}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const D=data,N=D.pages.length,hitPages=new Set(D.hits.flatMap(h=>h.pages));let sel=D.hits.length?D.hits[0].pages[0]:1,timers=[];
 const ST={appeal:["APPEAL","#5B2A86"],corrective_resubmission:["RESUBMIT","#C0446A"],specialist_review:["SPECIALIST REVIEW","#B4532F"]}[D.action];
 root.innerHTML=`<div class="ev"><div><div class="stamp" style="color:${ST[1]};border-color:${ST[1]}">${ST[0]}</div>
   <div class="reason">${D.reason}</div><div style="font-size:12.5px;color:#6E5C76">${D.why}</div>
   <div id="cites"></div></div>
  <div><div class="hdr"><div class="eyebrow">${N}-page chart · ${hitPages.size} page${hitPages.size===1?" holds":"s hold"} the evidence</div>
   <button class="btn ghost" id="go">Search the chart</button></div>
   <div class="card strip" id="strip"></div><div class="card reader" id="rd"></div></div></div>`;
 const strip=root.querySelector("#strip"),rd=root.querySelector("#rd");
 strip.innerHTML=D.pages.map((_,i)=>`<div class="pg read ${hitPages.has(i+1)?"hit":""}" data-p="${i+1}" title="page ${i+1}"></div>`).join("");
 const cites=root.querySelector("#cites");
 cites.innerHTML=D.hits.length?D.hits.map((h,k)=>`<div class="card cite" data-p="${h.pages[0]}" style="animation-delay:${k*80}ms">
   <div class="hdr"><span class="eyebrow">Page${h.pages.length>1?"s":""} ${h.pages.join(", ")}</span><span class="pill ${h.ok?"ok":"bad"}">${h.ok?"quote verified":"not found on page"}</span></div>
   <q>${h.quote.replace(/</g,"&lt;")}</q></div>`).join(""):`<div class="card cite" style="cursor:default">No passage in the chart meets the requirement, so there is nothing to cite.</div>`;
 const esc=s=>s.replace(/&/g,"&amp;").replace(/</g,"&lt;");
 function open(p){sel=p;strip.querySelectorAll(".pg").forEach(e=>e.classList.toggle("sel",+e.dataset.p===p));
  let txt=esc(D.pages[p-1]);D.hits.filter(h=>h.pages.includes(p)).forEach(h=>{h.quote.split(/\s*(?:;|\.\.\.|…)\s*/).filter(q=>q.length>12).forEach(q=>{
   const words=esc(q.trim()).split(/\s+/).slice(0,8).join(" ");const i=txt.indexOf(words);if(i>=0){const j=txt.indexOf("\n",i);const end=j<0?txt.length:Math.min(j,i+esc(q).length+40);
    txt=txt.slice(0,i)+"<mark>"+txt.slice(i,end)+"</mark>"+txt.slice(end)}})});
  rd.innerHTML=`<div class="eyebrow" style="font-family:'DM Sans',system-ui,sans-serif">Page ${p} of ${N}</div>\n${txt}`;const m=rd.querySelector("mark");if(m)m.scrollIntoView({block:"center",behavior:"smooth"})}
 strip.querySelectorAll(".pg").forEach(e=>e.onclick=()=>open(+e.dataset.p));cites.querySelectorAll(".cite[data-p]").forEach(c=>c.onclick=()=>open(+c.dataset.p));
 function search(){timers.forEach(clearTimeout);timers=[];const tiles=[...strip.querySelectorAll(".pg")];tiles.forEach(t=>t.classList.remove("read","hit","scan"));
  const step=Math.max(8,Math.min(40,2400/N));tiles.forEach((t,i)=>timers.push(setTimeout(()=>{t.classList.add("scan");
   timers.push(setTimeout(()=>{t.classList.remove("scan");t.classList.add(hitPages.has(i+1)?"hit":"read");if(hitPages.has(i+1))open(i+1)},step*2))},i*step)));}
 root.querySelector("#go").onclick=search;open(sel);search();
 return ()=>timers.forEach(clearTimeout);
}
"""

_component = st.components.v2.component("authops_evidence", css=CSS, js=JS)


def evidence_view(action: str, reason: str, why: str, pages: list[str], hits: list[dict], key: str) -> None:
    _component(data={"action": action, "reason": reason, "why": why, "pages": pages, "hits": hits}, key=key)
