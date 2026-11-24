"""Benefits widgets: a call transcript that plays turn by turn with both parsers' readings, and a live
patient-cost calculator that shows who pays for each visit."""
from __future__ import annotations

import streamlit as st

from app.widgets.theme import BASE_CSS

CALL_CSS = BASE_CSS + """
.wrap{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:18px}@media(max-width:900px){.wrap{grid-template-columns:1fr}}
.chat{padding:14px;max-height:780px;overflow:auto;display:flex;flex-direction:column;gap:8px}
.b{max-width:82%;padding:9px 12px;border-radius:14px;font-size:13px;line-height:1.4;animation:rise .3s ease both}
.b.q{align-self:flex-end;background:#1E0525;color:#fff;border-bottom-right-radius:4px}.b.a{align-self:flex-start;background:var(--cream);border:1px solid var(--sand);border-bottom-left-radius:4px}
.b .who{font:600 10px 'DM Sans',system-ui,sans-serif;letter-spacing:.1em;text-transform:uppercase;opacity:.6;display:block;margin-bottom:2px}
.f{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;align-items:center;padding:8px 12px;border-top:1px solid #F3EDE6;font-size:12.5px;opacity:.35;transition:opacity .3s}
.f.on{opacity:1}.f.h{opacity:1;font:500 10.5px 'DM Sans',system-ui,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);border:0}
.ok{color:#5B2A86}.no{color:#C0446A;font-weight:600}
.tot{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px}.tot .card{padding:10px 12px}.tot b{font:400 26px Fraunces,Georgia,serif;display:block}.tot span{font-size:11.5px;color:var(--muted)}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
"""

CALL_JS = r"""
export default function(component){
 const {data,parentElement}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const D=data,T=D.turns;let timers=[];
 root.innerHTML=`<div class="top"><div class="eyebrow">Benefits call · ${T.length} questions · as heard by speech-to-text</div><button class="btn ghost" id="go">Replay the call</button></div>
 <div class="wrap"><div class="card chat" id="chat"></div><div><div class="card" style="padding:4px 0">
  <div class="f h"><div>Field · truth</div><div>First number</div><div>Careful parser</div></div>
  ${T.map((t,i)=>`<div class="f" id="f${i}"><div><b>${t.field.replace(/_/g," ")}</b><br><span style="color:#8E8292">${t.truth}</span></div>
   <div class="${t.n_ok?"ok":"no"}">${t.naive} ${t.n_ok?"✓":"✕"}</div><div class="${t.c_ok?"ok":"no"}">${t.careful} ${t.c_ok?"✓":"✕"}</div></div>`).join("")}</div>
  <div class="tot"><div class="card"><b>${D.cost[0]}</b><span>true 12-visit cost</span></div><div class="card"><b style="color:${D.cost[1]===D.cost[0]?"#5B2A86":"#C0446A"}">${D.cost[1]}</b><span>quoted from first number</span></div>
   <div class="card"><b style="color:${D.cost[2]===D.cost[0]?"#5B2A86":"#C0446A"}">${D.cost[2]}</b><span>quoted from careful parser</span></div></div></div></div>`;
 const chat=root.querySelector("#chat");
 function play(){timers.forEach(clearTimeout);timers=[];chat.innerHTML="";T.forEach((_,i)=>root.querySelector("#f"+i).classList.remove("on"));
  T.forEach((t,i)=>{timers.push(setTimeout(()=>{chat.insertAdjacentHTML("beforeend",`<div class="b q"><span class="who">Agent</span>${t.q}</div>`);chat.scrollTop=chat.scrollHeight},i*900));
   timers.push(setTimeout(()=>{chat.insertAdjacentHTML("beforeend",`<div class="b a"><span class="who">Payor rep</span>${t.heard}</div>`);chat.scrollTop=chat.scrollHeight;root.querySelector("#f"+i).classList.add("on")},i*900+450))})}
 root.querySelector("#go").onclick=play;play();return ()=>timers.forEach(clearTimeout);
}
"""

CALC_CSS = BASE_CSS + """
.g{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px 18px}@media(max-width:800px){.g{grid-template-columns:repeat(2,1fr)}}
.in label{display:flex;justify-content:space-between;font-size:12px;color:var(--muted)}.in label b{font:400 18px Fraunces,Georgia,serif;color:var(--ink)}
.in input{width:100%;accent-color:#8C5FB9}
.big{display:flex;align-items:baseline;gap:14px;margin:16px 0 8px;flex-wrap:wrap}.big b{font:400 52px/1 Fraunces,Georgia,serif}.big span{color:var(--muted);font-size:13px}
.bars{padding:12px 14px}.legend{display:flex;gap:14px;font-size:11.5px;color:var(--muted);margin-top:6px;flex-wrap:wrap}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.mode{display:flex;gap:6px;margin:4px 0 12px}.mode button{font:500 12.5px 'DM Sans',system-ui,sans-serif;border:1px solid var(--sand);background:#fff;border-radius:999px;padding:6px 12px;cursor:pointer}.mode button.on{background:var(--ink);color:#fff;border-color:var(--ink)}
"""

CALC_JS = r"""
export default function(component){
 const {parentElement}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const F=[["deductible","Deductible",0,6000,50,1500,"$"],["deductible_met","Deductible met",0,6000,50,500,"$"],["coinsurance_pct","Coinsurance",0,50,1,20,"%"],
  ["oop_max","Out-of-pocket max",0,15000,100,5000,"$"],["oop_met","Out-of-pocket met",0,15000,50,800,"$"],["visit_limit","Visit limit (0 = none)",0,120,1,30,""],
  ["visits_used","Visits used",0,120,1,12,""],["allowed","Allowed per visit",20,600,5,150,"$"],["visits","Planned visits",1,60,1,24,""],["copay","Copay per visit",0,150,5,0,"$"]];
 const v={};F.forEach(f=>v[f[0]]=f[5]);
 root.innerHTML=`<div class="g">${F.map(f=>`<div class="in"><label>${f[1]}<b id="l_${f[0]}"></b></label><input type="range" id="${f[0]}" min="${f[2]}" max="${f[3]}" step="${f[4]}" value="${f[5]}"></div>`).join("")}</div>
  <div class="big"><b id="tot"></b><span id="sub"></span></div>
  <div class="card bars"><svg id="sv" viewBox="0 0 900 200" width="100%"></svg>
  <div class="legend"><span><i style="background:#C0446A"></i>toward the deductible</span><span><i style="background:#E0855F"></i>coinsurance or copay</span>
   <span><i style="background:#EFE7FA;border:1px solid #8C5FB9"></i>plan pays</span><span><i style="background:#1E0525"></i>past the visit limit</span></div></div>`;
 function calc(){let ded=Math.max(0,v.deductible-v.deductible_met),oop=Math.max(0,v.oop_max-v.oop_met);
  const lim=v.visit_limit?Math.max(0,v.visit_limit-v.visits_used):null,out=[];let tot=0;
  for(let i=0;i<v.visits;i++){const a=v.allowed;if(lim!==null&&i>=lim){out.push({d:0,c:0,x:a,p:0});tot+=a;continue}
   let d=0,c=0;if(v.copay){c=v.copay}else{d=Math.min(a,ded);ded-=d;c=(a-d)*v.coinsurance_pct/100}
   let pay=Math.min(d+c,oop);const s=d+c>0?pay/(d+c):0;d*=s;c*=s;oop-=pay;tot+=pay;out.push({d,c,x:0,p:a-pay})}
  return {out,tot}}
 function draw(){F.forEach(f=>root.querySelector("#l_"+f[0]).textContent=(f[6]==="$"?"$":"")+Number(v[f[0]]).toLocaleString()+(f[6]==="%"?"%":""));
  const {out,tot}=calc(),n=out.length,W=900,H=200,bw=Math.min(40,(W-20)/n-3),sc=(H-30)/v.allowed;let s="";
  out.forEach((o,i)=>{const x=10+i*(W-20)/n;let y=H-20;[[o.d,"#C0446A"],[o.c,"#E0855F"],[o.x,"#1E0525"],[o.p,"#EFE7FA"]].forEach(([h,c])=>{if(h<=0)return;
   y-=h*sc;s+=`<rect x="${x}" y="${y}" width="${bw}" height="${h*sc}" fill="${c}" ${c==="#EFE7FA"?'stroke="#8C5FB9" stroke-width=".7"':""} style="transition:all .3s"><title>visit ${i+1}: patient $${(o.d+o.c+o.x).toFixed(2)}</title></rect>`});
   if(n<=30||i%5===4)s+=`<text x="${x+bw/2}" y="${H-5}" font-size="10" text-anchor="middle" fill="#8E8292" font-family="DM Sans,system-ui,sans-serif">${i+1}</text>`});
  root.querySelector("#sv").innerHTML=s;root.querySelector("#tot").textContent="$"+tot.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const past=out.filter(o=>o.x>0).length;root.querySelector("#sub").textContent=`patient pays over ${v.visits} visits · $${(tot/v.visits).toFixed(2)} per visit on average${past?` · ${past} visits past the plan's limit`:""}`}
 F.forEach(f=>root.querySelector("#"+f[0]).oninput=e=>{v[f[0]]=+e.target.value;draw()});draw();
}
"""

_call = st.components.v2.component("authops_benefit_call", css=CALL_CSS, js=CALL_JS)
_calc = st.components.v2.component("authops_cost_calc", css=CALC_CSS, js=CALC_JS)


def call_player(turns: list[dict], cost: list[str], key: str) -> None:
    _call(data={"turns": turns, "cost": cost}, key=key)


def cost_calculator(key: str = "cost_calc") -> None:
    _calc(data={}, key=key)
