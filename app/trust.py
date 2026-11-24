"""Trust replay component: drag the hidden fault and the spot-check rate, press Play, watch two lines race."""
from __future__ import annotations

import json

import streamlit as st

HTML = r"""
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400&family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--ink:#1E0525;--violet:#5B2A86;--lilac:#8C5FB9;--rose:#C0446A;--peach:#FFB49D;--sand:#ECE5D8;--line:#F0EAE2;--cream:#FDF8F3;--muted:#8E8292}
*{box-sizing:border-box}body{margin:0;font-family:'DM Sans',system-ui,sans-serif;color:var(--ink);background:transparent}
.card{background:#fff;border:1px solid var(--sand);border-radius:20px;padding:20px 22px}
.ctl{display:grid;grid-template-columns:1fr 1fr auto;gap:18px;align-items:end}
@media(max-width:720px){.ctl{grid-template-columns:1fr}}
label .row{display:flex;justify-content:space-between;font-size:13px;color:var(--muted);margin-bottom:6px}
label .row b{color:var(--ink);font-variant-numeric:tabular-nums}
input[type=range]{width:100%}#fault{accent-color:var(--rose)}#audit{accent-color:var(--violet)}
.btn{border:0;background:var(--ink);color:#fff;font:600 13px 'DM Sans';padding:10px 20px;border-radius:999px;cursor:pointer}
.btn.ghost{background:#fff;color:var(--ink);border:1px solid var(--sand)}.btn:hover{transform:translateY(-1px)}
.duo{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}
.big{border-radius:16px;padding:14px 16px;color:#fff}.big span{font-size:12px;opacity:.85}
.big b{display:block;font:400 40px Fraunces,Georgia,serif;font-variant-numeric:tabular-nums;line-height:1.1}
svg{width:100%;display:block;margin-top:10px}
.foot{font-size:12px;color:var(--muted);margin-top:4px}
.lanes{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:14px}
@media(max-width:720px){.lanes{grid-template-columns:1fr}}
.lane{background:#fff;border:1px solid var(--sand);border-radius:18px;padding:16px 18px;transition:transform .2s,box-shadow .2s}
.lane:hover{transform:translateY(-2px);box-shadow:0 14px 28px -22px rgba(30,5,37,.5)}
.lh{display:flex;justify-content:space-between;align-items:center;gap:8px}.lh b{font-size:15px;text-transform:capitalize}
.tag{font:700 11px 'DM Sans';padding:3px 10px;border-radius:999px;white-space:nowrap;transition:all .3s}
.track{height:9px;background:var(--cream);border-radius:9px;margin-top:14px;overflow:hidden}
.fill{height:100%;border-radius:9px;transition:width .25s ease,background .3s}
.lt{font-size:12.5px;color:#4A3A50;margin-top:8px;min-height:34px}
</style>
<div class="card">
 <div class="ctl">
  <label><div class="row"><span>Hidden fault on Keystone from day 30</span><b id="fv"></b></div><input id="fault" type="range" min="0" max="4" step="1"></label>
  <label><div class="row"><span>Spot-check once trusted</span><b id="av"></b></div><input id="audit" type="range" min="0" max="3" step="1"></label>
  <div style="display:flex;gap:8px"><button class="btn" id="play">Play</button><button class="btn ghost" id="roll">Roll again</button></div>
 </div>
 <div class="duo">
  <div class="big" style="background:var(--rose)"><span>Wrong submissions reaching payors, trusted from day one</span><b id="n0">0</b></div>
  <div class="big" style="background:var(--violet)"><span>With the evidence-gated QA ramp</span><b id="n1">0</b></div>
 </div>
 <svg id="chart" viewBox="0 0 760 270"></svg>
 <div class="foot" id="foot"></div>
</div>
<div class="lanes" id="lanes"></div>
<script>
const D=__DATA__;const $=i=>document.getElementById(i);
let fi=3, ai=2, si=0, k=0, raf=null;
$("fault").value=fi;$("audit").value=ai;
const key=()=>`${D.faults[fi]}|${D.audits[ai]}|${D.seeds[si]}`;
const W=760,H=270,L=44,R=16,T=18,B=34;
const STATUS={earning:["Earning it","#FFE3D8","#B4532F"],ramping:["Review stepping down","#F4EDFB","#5B2A86"],
 trusted:["Sends on its own","#5B2A86","#fff"],stopped:["Stopped: back to review","#C0446A","#fff"]};
function labels(){$("fv").textContent=D.faults[fi]?Math.round(D.faults[fi]*100)+"% wrong":"none";$("av").textContent="1 in "+Math.round(1/D.audits[ai])}
function laneState(l,day){const tr=l.trace.slice(0,day+1),s=tr[tr.length-1]??1;
 const raised=tr.some((x,i)=>i&&x>tr[i-1]);const floor=D.audits[ai];
 const st=raised&&s>floor+1e-9?"stopped":s<=floor+1e-9?"trusted":s>=1?"earning":"ramping";
 return {s,st,runs:(day+1)*D.runs_per_day}}
function draw(){const r=D.grid[key()],n=D.days,mx=Math.max(1,...r.no_gate);
 const x=i=>L+i/(n-1)*(W-L-R),y=v=>T+(1-v/mx)*(H-T-B);
 const path=a=>a.slice(0,k).map((v,i)=>(i?"L":"M")+x(i).toFixed(1)+","+y(v).toFixed(1)).join("");
 const f=D.fault_day,showF=k>f&&D.faults[fi]>0;
 let s=`<rect x="${x(f)}" y="${T}" width="${x(n-1)-x(f)}" height="${H-T-B}" fill="#C0446A" opacity="${showF?.07:0}" style="transition:opacity .3s"/>`;
 if(showF)s+=`<text x="${x(f)+8}" y="${T+18}" font-size="14" font-weight="700" fill="#C0446A">fault starts</text>`;
 s+=`<line x1="${L}" x2="${W-R}" y1="${y(0)}" y2="${y(0)}" stroke="#ECE5D8"/>`;
 s+=`<text x="${L-8}" y="${y(mx)+5}" font-size="13" text-anchor="end" fill="#8E8292">${mx}</text><text x="${L-8}" y="${y(0)+5}" font-size="13" text-anchor="end" fill="#8E8292">0</text>`;
 s+=`<path d="${path(r.no_gate)}" fill="none" stroke="#C0446A" stroke-width="3.5" stroke-linejoin="round"/>`;
 s+=`<path d="${path(r.gate)}" fill="none" stroke="#5B2A86" stroke-width="3.5" stroke-linejoin="round"/>`;
 const mark=(d,txt,col,sq)=>{if(d==null||d>=k)return"";const cx=x(d),cy=y(r.gate[d]);
  return (sq?`<rect x="${cx-8}" y="${cy-8}" width="16" height="16" fill="${col}"/>`:`<circle cx="${cx}" cy="${cy}" r="8" fill="#FFB49D" stroke="#1E0525" stroke-width="2"/>`)+
   `<text x="${cx}" y="${cy-14}" font-size="14" font-weight="700" text-anchor="middle" fill="${col}">${txt}</text>`};
 s+=mark(r.trusted_day,"trusted","#1E0525",false)+mark(r.stopped_day,"stopped","#C0446A",true);
 s+=`<text x="${L}" y="${H-10}" font-size="13" fill="#8E8292">day 1</text><text x="${W-R}" y="${H-10}" font-size="13" text-anchor="end" fill="#8E8292">day ${n}</text>`;
 $("chart").innerHTML=s;
 $("n0").textContent=k?r.no_gate[k-1]:0;$("n1").textContent=k?r.gate[k-1]:0;
 const day=Math.max(0,k-1);
 $("lanes").innerHTML=r.lanes.map(l=>{const q=laneState(l,day),[w,bg,fg]=STATUS[q.st];
  const fill=q.st==="earning"?Math.min(1,q.runs/12):q.st==="trusted"?1:1-q.s;
  const col=q.st==="stopped"?"#C0446A":q.st==="earning"?"#FFB49D":"#8C5FB9";
  const txt=q.st==="earning"?`${Math.min(q.runs,12)} of 12 clean runs before review steps down`:
   q.st==="trusted"?`1 in ${Math.round(1/D.audits[ai])} runs still checked by a person`:
   q.st==="stopped"?`A reviewer caught a wrong submission; ${Math.round(q.s*100)}% of runs reviewed again`:`${Math.round(q.s*100)}% of runs reviewed`;
  return `<div class="lane"><div class="lh"><b>${l.portal}</b><span class="tag" style="background:${bg};color:${fg}">${w}</span></div>
   <div class="track"><div class="fill" style="width:${Math.max(3,fill*100)}%;background:${col}"></div></div><div class="lt">${txt}</div></div>`}).join("");
 $("foot").textContent=k>=n?`${D.runs_per_day*3*n} runs. Reviewers caught ${r.gate_caught} wrong submissions with the ramp and ${r.no_gate_caught} with fixed spot-checks. Only reviewed runs can reveal an error.`:"";}
function play(){cancelAnimationFrame(raf);const t0=performance.now(),dur=4800,n=D.days;
 const step=t=>{const f=Math.min(1,(t-t0)/dur);k=Math.max(1,Math.round(f*n));draw();if(f<1)raf=requestAnimationFrame(step)};raf=requestAnimationFrame(step)}
$("fault").oninput=e=>{fi=+e.target.value;labels();play()};$("audit").oninput=e=>{ai=+e.target.value;labels();play()};
$("play").onclick=play;$("roll").onclick=()=>{si=(si+1)%D.seeds.length;play()};
labels();play();
</script>
"""


def trust_replay(data: dict) -> None:
    st.iframe(HTML.replace("__DATA__", json.dumps(data, separators=(",", ":"))), height="content")
