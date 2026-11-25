"""Approval outlook: drag your request along the learned approval curve, against the real past decisions
from the same payor and service."""
from __future__ import annotations

import streamlit as st

from app.widgets.theme import BASE_CSS

CSS = BASE_CSS + """
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px}
.tile{padding:14px 16px}.tile b{display:block;font:400 38px/1.05 Fraunces,Georgia,serif;transition:color .2s}
.tile span{font-size:12px;color:var(--muted)}.tile.rec{background:linear-gradient(135deg,#FDF8F3,#FAE8E8)}
.plot{padding:12px 14px;position:relative}svg text{font-family:'DM Sans',sans-serif}
.legend{display:flex;gap:14px;font-size:12px;color:var(--muted);margin:2px 4px 6px;flex-wrap:wrap;align-items:center}
.legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:-1px}
.tip{position:absolute;pointer-events:none;background:#1E0525;color:#fff;font-size:12px;padding:7px 10px;border-radius:8px;opacity:0;transition:opacity .15s;white-space:nowrap}
.row{display:flex;gap:8px;margin-top:10px;align-items:center;flex-wrap:wrap}
.hint{font-size:12px;color:var(--muted);margin-left:auto}
"""

JS = r"""
export default function(component){
 const {data,parentElement}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const D=data,C=D.curve,maxU=C[C.length-1].units;let u=D.units;
 const W=900,H=300,L=56,R=20,T=16,B=40,x=v=>L+v/maxU*(W-L-R),y=p=>T+(1-p)*(H-T-B);
 const at=v=>{let i=C.findIndex(c=>c.units>=v);if(i<=0)return C[Math.max(0,i)];const a=C[i-1],b=C[i],t=(v-a.units)/(b.units-a.units);
  return {units:v,p:a.p+(b.p-a.p)*t,exp:a.exp+(b.exp-a.exp)*t}};
 root.innerHTML=`<div class="tiles"><div class="card tile"><b id="tp"></b><span id="tpl"></span></div>
  <div class="card tile"><b id="te"></b><span>units expected on first pass</span></div>
  <div class="card tile rec"><b>${D.rec}</b><span>recommended: largest request that clears ${Math.round(D.target*100)}%</span></div></div>
  <div class="card plot"><div class="legend"><span><i style="background:#5B2A86"></i>approved in full</span><span><i style="background:#E0855F"></i>cut to partial</span>
   <span><i style="background:#C0446A"></i>denied</span><span>· ${D.dots.length} past decisions, same payor and service, similar severity</span></div>
   <svg id="sv" viewBox="0 0 ${W} ${H}" width="100%" style="touch-action:none;cursor:ew-resize"></svg><div class="tip" id="tip"></div>
   <div class="row"><button class="btn" id="userec">Use recommended</button><button class="btn ghost" id="usecur">Back to ${D.units}</button>
   <span class="hint">Drag across the chart to try a different request. Hover a dot to see that decision.</span></div></div>`;
 const sv=root.querySelector("#sv"),tip=root.querySelector("#tip");
 let base=`<rect x="${L}" y="${y(1)}" width="${W-L-R}" height="${y(D.target)-y(1)}" fill="#EFE7FA" opacity=".55"/>`;
 [0,.25,.5,.75,1].forEach(p=>base+=`<line x1="${L}" x2="${W-R}" y1="${y(p)}" y2="${y(p)}" stroke="#F0EAE2"/><text x="${L-8}" y="${y(p)+4}" font-size="11" text-anchor="end" fill="#8E8292">${p*100}%</text>`);
 for(let k=0;k<=5;k++){const v=Math.round(maxU*k/5);base+=`<text x="${x(v)}" y="${H-B+18}" font-size="11" text-anchor="middle" fill="#8E8292">${v}</text>`}
 base+=`<text x="${(W+L)/2}" y="${H-4}" font-size="11.5" text-anchor="middle" fill="#6E5C76">units requested</text>`;
 base+=`<line x1="${L}" x2="${W-R}" y1="${y(D.target)}" y2="${y(D.target)}" stroke="#8C5FB9" stroke-dasharray="4 4"/><text x="${W-R}" y="${y(D.target)-6}" font-size="11" text-anchor="end" fill="#5B2A86">target ${Math.round(D.target*100)}%</text>`;
 const col={approved:"#5B2A86",partial:"#E0855F",denied:"#C0446A"};
 D.dots.forEach((d,i)=>{const yy=d.o==="approved"?y(1)+10+(i*13%40):d.o==="partial"?y(0)-10-(i*13%40):y(0)-4;
  base+=`<circle class="pd" data-i="${i}" cx="${x(Math.min(d.q,maxU))}" cy="${yy}" r="4.2" fill="${col[d.o]}" opacity=".55" stroke="#fff" stroke-width=".8"/>`});
 const path=C.map((c,i)=>`${i?"L":"M"}${x(c.units)},${y(c.p)}`).join("");
 base+=`<path d="${path}" fill="none" stroke="#5B2A86" stroke-width="3" stroke-linecap="round" id="cv"/>`;
 base+=`<line x1="${x(D.rec)}" x2="${x(D.rec)}" y1="${T}" y2="${H-B}" stroke="#5B2A86" stroke-dasharray="2 3" opacity=".6"/>`;
 sv.innerHTML=base+`<g id="me"></g>`;const cv=sv.querySelector("#cv"),len=cv.getTotalLength();
 cv.style.strokeDasharray=len;cv.style.strokeDashoffset=len;cv.getBoundingClientRect();cv.style.transition="stroke-dashoffset 1.1s ease";cv.style.strokeDashoffset=0;
 function draw(){const a=at(u),me=sv.querySelector("#me"),ok=a.p>=D.target;
  me.innerHTML=`<line x1="${x(u)}" x2="${x(u)}" y1="${T}" y2="${H-B}" stroke="#E0855F" stroke-width="2"/>
   <circle cx="${x(u)}" cy="${y(a.p)}" r="9" fill="#fff" stroke="#E0855F" stroke-width="3"/>
   <rect x="${Math.min(x(u)+10,W-R-128)}" y="${Math.max(T+4,y(a.p)-34)}" width="118" height="24" rx="12" fill="#1E0525"/>
   <text x="${Math.min(x(u)+10,W-R-128)+59}" y="${Math.max(T+4,y(a.p)-34)+16}" font-size="12" text-anchor="middle" fill="#fff">${Math.round(u)} units · ${Math.round(a.p*100)}%</text>`;
  const tp=root.querySelector("#tp");tp.textContent=Math.round(a.p*100)+"%";tp.style.color=ok?"#5B2A86":"#C0446A";
  root.querySelector("#tpl").textContent=`chance of full approval at ${Math.round(u)} units`;
  root.querySelector("#te").textContent=Math.round(a.exp)}
 const toU=e=>{const r=sv.getBoundingClientRect();return Math.max(1,Math.min(maxU,((e.clientX-r.left)/r.width*W-L)/(W-L-R)*maxU))};
 let drag=false;sv.addEventListener("pointerdown",e=>{drag=true;sv.setPointerCapture(e.pointerId);u=Math.round(toU(e));draw()});
 sv.addEventListener("pointermove",e=>{if(drag){u=Math.round(toU(e));draw()}const t=e.target;
  if(t.classList&&t.classList.contains("pd")){const d=D.dots[+t.dataset.i],r=root.querySelector(".plot").getBoundingClientRect();
   tip.innerHTML=`Week ${d.w} · severity ${d.s.toFixed(2)} · asked ${d.q} · got ${d.a}`;tip.style.left=(e.clientX-r.left+12)+"px";tip.style.top=(e.clientY-r.top-30)+"px";tip.style.opacity=1}else tip.style.opacity=0});
 sv.addEventListener("pointerup",()=>drag=false);sv.addEventListener("pointerleave",()=>{tip.style.opacity=0});
 const anim=to=>{const f=u,t0=performance.now();const st=t=>{const k=Math.min(1,(t-t0)/500),e=1-Math.pow(1-k,3);u=f+(to-f)*e;draw();if(k<1)requestAnimationFrame(st)};requestAnimationFrame(st)};
 root.querySelector("#userec").onclick=()=>anim(D.rec);root.querySelector("#usecur").onclick=()=>anim(D.units);
 draw();
}
"""

_component = st.components.v2.component("authops_outlook", css=CSS, js=JS)


def approval_outlook(curve: list[dict], dots: list[dict], units: int, rec: int, target: float, key: str) -> None:
    _component(data={"curve": curve, "dots": dots, "units": units, "rec": rec, "target": target}, key=key)
