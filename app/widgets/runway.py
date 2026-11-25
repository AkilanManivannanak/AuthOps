"""Runway: every patient with an active authorization, placed by days of care left. Dots never overlap (each is
stacked into the first free row of its lane) and details open in a side panel, never on top of other dots."""
from __future__ import annotations

import streamlit as st

from app.widgets.theme import BASE_CSS

CSS = BASE_CSS + """
.wrap{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:16px}@media(max-width:900px){.wrap{grid-template-columns:1fr}}
.chart{border:1px solid var(--sand);border-radius:20px;background:#fff;padding:12px 14px}
svg text{font-family:'DM Sans',system-ui,sans-serif}
.dot{cursor:pointer;transition:r .15s,stroke-width .15s}
.side{border:1px solid var(--sand);border-radius:20px;background:#fff;padding:18px 18px;align-self:start;position:sticky;top:10px}
.side .e{color:var(--muted);font-size:13px}
.side h4{margin:4px 0 2px;font:400 22px Fraunces,Georgia,serif}.side .m{color:var(--muted);font-size:12.5px}
.kv{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}.kv div{font:400 20px Fraunces,Georgia,serif}
.kv span{display:block;font:500 10px 'DM Sans',system-ui,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.bar{height:10px;border-radius:9px;background:#F4EFF6;overflow:hidden}.bar i{display:block;height:100%;background:#8C5FB9;border-radius:9px}
.note{font-size:12.5px;line-height:1.5;background:var(--cream);border-radius:12px;padding:10px 12px;margin-top:12px}
.go{margin-top:12px;width:100%}
.tag{display:inline-block;font:600 11px 'DM Sans',system-ui,sans-serif;border-radius:999px;padding:3px 9px;margin-top:8px}
"""

JS = r"""
export default function(component){
 const {data,parentElement,setTriggerValue}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const D=data,P=D.patients,LANES=[["due","Reauth due","#C0446A"],["sent","Reauth sent","#4B4F8A"],["ok","On track","#5B2A86"]];
 const W=760,L=110,R=20,T=34,Rd=10,ROW=24,maxD=Math.max(120,...P.map(p=>p.days));
 const x=d=>L+Math.min(d,maxD)/maxD*(W-L-R);
 // stack dots: first row in the lane where no placed dot is within 2 radii + label room
 const rows={};P.forEach(p=>{const placed=(rows[p.lane]=rows[p.lane]||[]);let r=0;
  while(placed.some(q=>q.r===r&&Math.abs(x(q.days)-x(p.days))<Rd*2+64))r++;placed.push({r,days:p.days});p.row=r});
 const laneH=LANES.map(([k])=>Math.max(1,...(rows[k]||[{r:0}]).map(q=>q.r+1))*ROW+18);
 const laneY=[];let acc=T;laneH.forEach(h=>{laneY.push(acc);acc+=h});const H=acc+28;
 let sel=D.focus&&P.find(p=>p.id===D.focus)?D.focus:(P.find(p=>p.lane==="due")||P[0]||{}).id;
 root.innerHTML=`<div class="wrap"><div class="chart"><svg id="sv" viewBox="0 0 ${W} ${H}" width="100%"></svg></div><div class="side" id="side"></div></div>`;
 function draw(){let s="";const lead=Math.max(0,...P.map(p=>p.lead));
  s+=`<rect x="${x(0)}" y="${T-6}" width="${x(lead)-x(0)}" height="${acc-T+6}" fill="#FFB49D" opacity=".16" rx="8"/>
   <text x="${(x(0)+x(lead))/2}" y="${H-22}" font-size="11" text-anchor="middle" fill="#B4532F">reauth window</text>`;
  [0,30,60,90,120].filter(d=>d<=maxD).forEach(d=>s+=`<text x="${x(d)}" y="${H-8}" font-size="11" text-anchor="middle" fill="#8E8292">${d===0?"today":d+" d"}</text>`);
  LANES.forEach(([k,n,c],i)=>{s+=`<text x="10" y="${laneY[i]+16}" font-size="12.5" fill="${c}" font-weight="600">${n}</text>
   <line x1="${L}" x2="${W-R}" y1="${laneY[i]+laneH[i]-4}" y2="${laneY[i]+laneH[i]-4}" stroke="#F3EDE6"/>`});
  P.forEach(p=>{const li=LANES.findIndex(l=>l[0]===p.lane),cy=laneY[li]+12+p.row*ROW,cx=x(p.days),on=p.id===sel,c=LANES[li][2];
   s+=`<g class="dot" data-id="${p.id}"><circle cx="${cx}" cy="${cy}" r="${on?Rd+3:Rd}" fill="${c}" opacity="${on?1:.85}" stroke="${on?"#1E0525":"#fff"}" stroke-width="${on?3:2}"/>
    <text x="${cx>W-R-70?cx-Rd-6:cx+Rd+6}" text-anchor="${cx>W-R-70?"end":"start"}" y="${cy+4}" font-size="12" fill="#1E0525" font-weight="${on?700:500}">${p.first}</text></g>`});
  root.querySelector("#sv").innerHTML=s;
  root.querySelectorAll(".dot").forEach(g=>{g.onclick=()=>{sel=g.dataset.id;draw();side()};g.onmouseenter=()=>{if(g.dataset.id!==sel){sel=g.dataset.id;draw();side()}}})}
 function side(){const p=P.find(q=>q.id===sel),el=root.querySelector("#side");
  if(!p){el.innerHTML=`<div class="e">No active authorizations yet. Approved requests appear here.</div>`;return}
  const tag={due:["Reauth due","#FBEAF1","#A8355F"],sent:["Reauth sent","#EEF0FA","#4B4F8A"],ok:["On track","#EFE7FA","#5B2A86"]}[p.lane];
  el.innerHTML=`<div class="m">${p.service} · ${p.payor}</div><h4>${p.name}</h4><span class="tag" style="background:${tag[1]};color:${tag[2]}">${tag[0]}</span>
   <div class="kv"><div><span>Care left</span>${p.days} days</div><div><span>${p.unit} left</span>${p.left} of ${p.approved}</div>
   <div><span>Start reauth by</span>${p.reauth_on}</div><div><span>Payor needs</span>${p.lead} days</div></div>
   <div class="bar"><i style="width:${Math.round(100*p.used/Math.max(1,p.approved))}%"></i></div>
   <div class="note">${p.lane==="due"?`Care runs out in ${p.days} days and ${p.payor} can take up to ${p.lead} days to decide. Start now so visits don't pause.`:
     p.lane==="sent"?`Reauthorization sent ${p.sent}. Waiting on ${p.payor}.`:`Nothing to do yet. AuthOps will flag this on ${p.reauth_on}.`}</div>
   ${p.lane==="due"?`<button class="btn go" id="go">Start the reauthorization</button>`:""}`;
  const b=el.querySelector("#go");if(b)b.onclick=()=>setTriggerValue("reauth",p.id)}
 draw();side();
}
"""

_component = st.components.v2.component("authops_runway", css=CSS, js=JS)


def runway_board(patients: list[dict], focus: str | None, key: str) -> str | None:
    res = _component(data={"patients": patients, "focus": focus}, key=key, on_reauth_change=lambda: None)
    return getattr(res, "reauth", None)
