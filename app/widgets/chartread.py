"""Long-chart reader: both arms read the same chart; each rule's verdict lands against the answer key,
and clicking a rule lights the pages that decide it."""
from __future__ import annotations

import streamlit as st

from app.widgets.theme import BASE_CSS

CSS = BASE_CSS + """
.wrap{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:18px}
@media(max-width:900px){.wrap{grid-template-columns:1fr}}
.score{display:flex;gap:12px;margin-bottom:12px}.score .card{flex:1;padding:12px 14px}
.score b{font:400 34px/1 Fraunces,Georgia,serif;display:block}.score span{font-size:12px;color:var(--muted)}
.rules{padding:6px 0}.r{display:grid;grid-template-columns:1fr 70px 96px 96px;gap:8px;align-items:center;padding:9px 14px;cursor:pointer;border-top:1px solid #F3EDE6;transition:background .15s}
.r:hover,.r.sel{background:#FBF6FF}.r.h{cursor:default;background:none;font:500 10.5px 'DM Sans',system-ui,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);border-top:0}
.r .n{font-size:13px;line-height:1.3}.r .n small{display:block;color:var(--muted);font-size:11.5px}
.v{font:600 11px 'DM Sans',system-ui,sans-serif;letter-spacing:.06em;text-transform:uppercase;border-radius:999px;padding:4px 8px;text-align:center;opacity:0;transform:scale(.6);transition:opacity .25s,transform .35s cubic-bezier(.3,1.6,.5,1)}
.v.on{opacity:1;transform:none}.v.right{background:#EFE7FA;color:#5B2A86}.v.wrong{background:#FBEAF1;color:#A8355F;box-shadow:0 0 0 2px #F4B9CF}.v.asked{background:#FFF0E8;color:#B4532F}
.key{font:600 11px 'DM Sans',system-ui,sans-serif;text-align:center}
.strip{display:grid;grid-template-columns:repeat(auto-fill,minmax(14px,1fr));gap:3px;padding:12px;perspective:600px}
.pg{height:22px;border-radius:3px;background:#F7F1EC;border:1px solid var(--sand);cursor:pointer;position:relative;transition:transform .15s,background .25s}
.pg:hover{transform:translateY(-3px) rotateX(14deg)}.pg.hw{background-image:repeating-linear-gradient(135deg,transparent 0 3px,rgba(140,95,185,.18) 3px 4px)}
.pg.scan{background:#FFB49D}.pg.key{background:#FFB49D;border-color:#E0855F}.pg.a0{box-shadow:inset 0 -4px 0 #8E8292}.pg.a1{box-shadow:inset 0 4px 0 #5B2A86}
.pg.a0.a1{box-shadow:inset 0 4px 0 #5B2A86,inset 0 -4px 0 #8E8292}.pg.sel{outline:2px solid #1E0525;outline-offset:1px}
.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:11.5px;color:var(--muted);margin:8px 2px}.legend i{display:inline-block;width:12px;height:9px;border-radius:2px;margin-right:4px;vertical-align:-1px}
.reader{padding:14px 16px;margin-top:10px;max-height:300px;overflow:auto;white-space:pre-wrap;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;color:#3A2A40}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
"""

JS = r"""
export default function(component){
 const {data,parentElement}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const D=data,N=D.pages.length,R=D.rules;let sel=null,page=R[0].key[0]||1,timers=[];
 const right=(v,t)=>(v==="pass")===t;
 const chip=(v,t)=>v==="pass"||v==="fail"?`<div class="v ${right(v,t)?"right":"wrong"}">${v}${right(v,t)?"":" ✕"}</div>`:`<div class="v asked">${v.replace("_"," ")}</div>`;
 const sc=a=>R.filter(r=>right(r.arms[a].v,r.truth)).length,fp=a=>R.filter(r=>r.arms[a].v==="pass"&&!r.truth).length;
 root.innerHTML=`<div class="top"><div class="eyebrow">${N}-page chart · ${D.hw.length} handwritten-style scans · ${D.spec}</div><button class="btn ghost" id="go">Replay the read</button></div>
 <div class="wrap"><div><div class="score">${D.arms.map((a,i)=>`<div class="card"><b>${sc(i)}/${R.length}</b><span>${a} · ${fp(i)} false pass${fp(i)===1?"":"es"}</span></div>`).join("")}</div>
  <div class="card rules"><div class="r h"><div>Rule</div><div style="text-align:center">Answer</div><div style="text-align:center">${D.arms[0]}</div><div style="text-align:center">${D.arms[1]}</div></div>
  ${R.map((r,i)=>`<div class="r" data-i="${i}"><div class="n">${r.name}<small>${r.text}</small></div><div class="key" style="color:${r.truth?"#5B2A86":"#C0446A"}">${r.truth?"pass":"FAIL"}</div>${chip(r.arms[0].v,r.truth)}${chip(r.arms[1].v,r.truth)}</div>`).join("")}</div></div>
 <div><div class="card strip" id="strip"></div>
  <div class="legend"><span><i style="background:#FFB49D"></i>deciding page</span><span><i style="background:#fff;box-shadow:inset 0 3px 0 #5B2A86"></i>${D.arms[1]} cited</span>
   <span><i style="background:#fff;box-shadow:inset 0 -3px 0 #8E8292"></i>${D.arms[0]} cited</span><span><i style="background-image:repeating-linear-gradient(135deg,transparent 0 3px,rgba(140,95,185,.35) 3px 4px)"></i>handwritten scan</span></div>
  <div class="card reader" id="rd"></div></div></div>`;
 const strip=root.querySelector("#strip"),rd=root.querySelector("#rd");
 strip.innerHTML=D.pages.map((_,i)=>`<div class="pg ${D.hw.includes(i+1)?"hw":""}" data-p="${i+1}" title="page ${i+1}"></div>`).join("");
 const tiles=[...strip.children];
 function paint(){tiles.forEach((t,i)=>{const p=i+1,r=sel===null?null:R[sel];t.classList.toggle("key",!!r&&r.key.includes(p));
   t.classList.toggle("a0",!!r&&r.arms[0].p.includes(p));t.classList.toggle("a1",!!r&&r.arms[1].p.includes(p));t.classList.toggle("sel",p===page)});
  root.querySelectorAll(".r[data-i]").forEach(e=>e.classList.toggle("sel",+e.dataset.i===sel));
  const esc=s=>s.replace(/&/g,"&amp;").replace(/</g,"&lt;");
  rd.innerHTML=`<span class="eyebrow" style="font-family:'DM Sans',system-ui,sans-serif">Page ${page} of ${N}${R.some(r=>r.key.includes(page))?" · deciding page for "+R.filter(r=>r.key.includes(page)).map(r=>r.name).join(", "):""}${D.hw.includes(page)?" · handwritten scan":""}</span>\n${esc(D.pages[page-1])}`}
 root.querySelectorAll(".r[data-i]").forEach(e=>e.onclick=()=>{sel=+e.dataset.i;page=R[sel].key[0]||page;paint()});
 tiles.forEach(t=>t.onclick=()=>{page=+t.dataset.p;paint()});
 function replay(){timers.forEach(clearTimeout);timers=[];const chips=[...root.querySelectorAll(".v")];chips.forEach(c=>c.classList.remove("on"));
  const step=Math.max(6,Math.min(30,1800/N));tiles.forEach((t,i)=>timers.push(setTimeout(()=>{t.classList.add("scan");timers.push(setTimeout(()=>t.classList.remove("scan"),step*3))},i*step)));
  chips.forEach((c,k)=>timers.push(setTimeout(()=>c.classList.add("on"),N*step+k*90)))}
 root.querySelector("#go").onclick=replay;paint();replay();
 return ()=>timers.forEach(clearTimeout);
}
"""

_component = st.components.v2.component("authops_chart_read", css=CSS, js=JS)


def chart_read(pages, handwritten, spec, arms, rules, key):
    _component(data={"pages": pages, "hw": list(handwritten), "spec": spec, "arms": arms, "rules": rules}, key=key)
