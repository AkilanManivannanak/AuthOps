"""Coverage board: every patient's authorization runway as a dot. Drag the day forward to see who slides
into the reauthorization window if nobody acts; click a dot for the burn-down."""
from __future__ import annotations

import streamlit as st

from app.widgets.theme import BASE_CSS

CSS = BASE_CSS + """
.top{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
.chip{font:500 12.5px 'DM Sans',system-ui,sans-serif;border:1px solid var(--sand);background:#fff;border-radius:999px;padding:6px 12px;cursor:pointer;display:inline-flex;gap:7px;align-items:center}
.chip i{width:9px;height:9px;border-radius:50%}.chip.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.risk{margin-left:auto;text-align:right}.risk b{font:400 28px Fraunces,Georgia,serif;color:#C0446A}.risk span{font-size:12px;color:var(--muted);display:block}
.board{padding:10px 12px;overflow-x:auto}
svg text{font-family:'DM Sans',sans-serif}
.dot{cursor:pointer;transition:cx .5s cubic-bezier(.2,.8,.2,1),cy .5s,opacity .25s,r .2s}
.time{display:flex;align-items:center;gap:14px;margin-top:12px}.time input{flex:1;accent-color:#8C5FB9}
.day{font:400 22px Fraunces,Georgia,serif;min-width:150px}
.drawer{position:fixed;top:0;right:0;bottom:0;width:400px;max-width:94vw;background:#fff;border-left:1px solid var(--sand);z-index:999999;
 box-shadow:-30px 0 60px -40px rgba(30,5,37,.5);transform:translateX(105%);transition:transform .35s cubic-bezier(.2,.8,.2,1);padding:24px;overflow:auto}
.drawer.open{transform:none}.x{position:absolute;right:18px;top:14px;cursor:pointer;color:var(--muted);font-size:18px}
.stamp{display:inline-block;transform:rotate(-4deg);border:3px solid;border-radius:10px;padding:3px 12px;font:800 15px 'DM Sans',system-ui,sans-serif;letter-spacing:.14em;margin:12px 0}
.kv{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0}.kv div{font:400 20px Fraunces,Georgia,serif}
.kv span{display:block;font:500 10px 'DM Sans',system-ui,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.ub{height:12px;background:var(--cream);border-radius:9px;overflow:hidden;display:flex}
.note{background:var(--cream);border-radius:12px;padding:12px;font-size:12.5px;line-height:1.5;margin-top:12px}
"""

JS = r"""
export default function(component){
 const {data,parentElement}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const D=data,P=D.patients;let day=0,lane="all",spec="all",sel=null;
 const SPEC={aba:["ABA","#8C5FB9"],physical_therapy:["PT","#E0855F"],behavioral_health:["BH","#32073E"]};
 const LANES=[["now","Start reauth now","#C0446A"],["units","Units run out first","#E0855F"],["date","End date first","#8C5FB9"],["coverage","Coverage changed","#1E0525"]];
 const lead=p=>Math.round(D.p90[p.plan]*7/5+D.buffer);
 function state(p,d){const upw=p.vpw*D.upv[p.spec];const left=Math.max(0,p.approved-p.used-d/7*upw);const dl=p.end-d;
  const wte=upw>0?left/upw*7:1e9;const run=Math.max(-10,Math.min(dl,wte));const L=lead(p);
  const lane=(p.covered<=d||(p.switch!==null&&p.switch<=d))?"coverage":run<=L?"now":wte<dl?"units":"date";
  return {left,dl,wte,run,L,lane,upw,rev:p.vpw*D.rate[p.spec]}}
 root.innerHTML=`<div class="top" id="chips"></div><div class="card board"><svg id="sv" viewBox="0 0 980 300" style="min-width:720px;width:100%"></svg></div>
  <div class="time"><button class="btn" id="play">Play 8 weeks</button><input type="range" id="d" min="0" max="56" value="0"><div class="day" id="dl">Today</div></div>
  <div class="drawer" id="dr"></div>`;
 const sv=root.querySelector("#sv"),dr=root.querySelector("#dr");
 const X=r=>130+Math.max(-10,Math.min(120,r))/130*820+10/130*820, LY=i=>44+i*60;
 function chips(){const S=P.map(p=>state(p,day));const cnt=k=>S.filter(s=>s.lane===k&&(spec==="all"||P[S.indexOf(s)].spec===spec)).length;
  const risk=P.reduce((t,p,i)=>t+((S[i].lane==="now"||S[i].lane==="coverage")&&(spec==="all"||p.spec===spec)?S[i].rev:0),0);
  root.querySelector("#chips").innerHTML=`<button class="chip ${lane==="all"?"on":""}" data-l="all">All ${P.length}</button>`+
   LANES.map(([k,n,c])=>`<button class="chip ${lane===k?"on":""}" data-l="${k}"><i style="background:${c}"></i>${n} ${cnt(k)}</button>`).join("")+
   `<span style="width:8px"></span>`+["all","aba","physical_therapy","behavioral_health"].map(s=>`<button class="chip ${spec===s?"on":""}" data-s="${s}">${s==="all"?"All services":SPEC[s][0]}</button>`).join("")+
   `<div class="risk"><b>$${Math.round(risk).toLocaleString()}</b><span>billed per week at risk in red lanes</span></div>`;
  root.querySelectorAll("[data-l]").forEach(b=>b.onclick=()=>{lane=b.dataset.l;draw()});
  root.querySelectorAll("[data-s]").forEach(b=>b.onclick=()=>{spec=b.dataset.s;draw()})}
 function draw(){chips();const S=P.map(p=>state(p,day));let s="";
  LANES.forEach(([k,n,c],i)=>{s+=`<line x1="130" x2="960" y1="${LY(i)}" y2="${LY(i)}" stroke="#F0EAE2"/><circle cx="14" cy="${LY(i)}" r="5" fill="${c}"/>
   <text x="26" y="${LY(i)+4}" font-size="12" fill="#1E0525">${n}</text>`});
  const lo=X(D.lead_lo),hi=X(D.lead_hi);
  s+=`<rect x="${X(-10)}" y="18" width="${X(0)-X(-10)}" height="230" fill="#C0446A" opacity=".06"/><text x="${X(-10)+4}" y="268" font-size="11" fill="#C0446A">Auth lapsed</text>`;
  s+=`<rect x="${X(0)}" y="18" width="${hi-X(0)}" height="230" fill="#FFB49D" opacity=".18"/><line x1="${hi}" x2="${hi}" y1="18" y2="248" stroke="#E0855F" stroke-width="2.5"/>
   <text x="${hi+5}" y="268" font-size="11" fill="#B4532F">reauth window (payor p90 + ${D.buffer}d buffer)</text>`;
  s+=`<text x="${X(120)}" y="268" font-size="11" text-anchor="end" fill="#8E8292">120+ days of runway</text><text x="${X(0)}" y="12" font-size="11" text-anchor="middle" fill="#1E0525" font-weight="600">0 days</text>`;
  P.forEach((p,i)=>{const st=S[i],li=LANES.findIndex(l=>l[0]===st.lane),on=(lane==="all"||lane===st.lane)&&(spec==="all"||spec===p.spec);
   const r=3+6*Math.sqrt(st.rev/D.maxrev),cy=LY(li)+((i*7)%30)-15;
   s+=`<circle class="dot" data-i="${i}" cx="${X(st.run)}" cy="${cy}" r="${sel===i?r+3:r}" fill="${SPEC[p.spec][1]}" stroke="${sel===i?"#1E0525":"#fff"}" stroke-width="${sel===i?2.5:1}" opacity="${on?.85:.08}"><title>${p.pid} · ${SPEC[p.spec][0]} · ${Math.round(st.run)} days</title></circle>`});
  sv.innerHTML=s;sv.querySelectorAll(".dot").forEach(c=>c.onclick=()=>{sel=+c.dataset.i;draw();drawer()});
  root.querySelector("#dl").textContent=day?`Day ${day} · if nobody acts`:"Today";if(sel!==null)drawer()}
 function drawer(){const p=P[sel],s=state(p,day);const st=s.lane==="coverage"?["VERIFY COVERAGE","#1E0525"]:s.lane==="now"?["START REAUTH","#C0446A"]:["WATCH","#5B2A86"];
  const W=340,H=120,maxd=Math.max(30,Math.ceil(Math.min(s.dl,s.wte))+14);const x=d=>10+d/maxd*(W-20),y=u=>10+(1-u/p.approved)*(H-30);
  const pts=[];for(let d=0;d<=maxd;d+=2)pts.push(`${x(d)},${y(Math.max(0,s.left-d/7*s.upw))}`);
  dr.innerHTML=`<span class="x" id="dx">✕</span><div class="eyebrow">${p.pid} · ${SPEC[p.spec][0]} · ${p.plan.replace("_"," ")}</div>
   <div class="stamp" style="color:${st[1]};border-color:${st[1]}">${st[0]}</div>
   <div class="kv"><div><span>Runway</span>${Math.max(0,Math.round(s.run))} days</div><div><span>Reauth lead</span>${s.L} days</div>
   <div><span>Units left</span>${Math.round(s.left)} of ${p.approved}</div><div><span>Billed per week</span>$${Math.round(s.rev)}</div></div>
   <div class="ub"><i style="width:${(1-s.left/p.approved)*100}%;background:#8C5FB9"></i></div>
   <div class="eyebrow" style="margin:14px 0 6px">Burn-down if nobody acts</div>
   <svg viewBox="0 0 ${W} ${H}" width="100%"><line x1="10" x2="${W-10}" y1="${H-20}" y2="${H-20}" stroke="#ECE5D8"/>
    <polyline points="${pts.join(" ")}" fill="none" stroke="#8C5FB9" stroke-width="3"/>
    ${s.dl<=maxd?`<line x1="${x(s.dl)}" x2="${x(s.dl)}" y1="6" y2="${H-20}" stroke="#1E0525" stroke-dasharray="3 3"/><text x="${x(s.dl)}" y="${H-6}" font-size="10" text-anchor="middle" fill="#1E0525">auth ends</text>`:""}
    <rect x="${x(Math.max(0,s.run-s.L))}" y="6" width="${Math.max(2,x(s.run)-x(Math.max(0,s.run-s.L)))}" height="${H-26}" fill="#FFB49D" opacity=".25"/>
    <text x="${x(Math.max(0,s.run-s.L))+3}" y="18" font-size="10" fill="#B4532F">start reauth by here</text></svg>
   <div class="note">${s.lane==="coverage"?"The weekly eligibility check found this patient's coverage changed. Verify the new plan before the next visit, or every visit after this is unpaid.":
    s.lane==="now"?`Runway is ${Math.max(0,Math.round(s.run))} days, inside the ${s.L}-day lead this ${p.plan.replace("_"," ")} payor needs (90th percentile turnaround plus buffer). Start the reauthorization now so care doesn't pause.`:
    `Limited by the ${s.lane==="units"?"units":"end date"}. The monitor starts the reauthorization ${Math.max(0,Math.round(s.run-s.L))} days from now.`}</div>
   <div style="font-size:11.5px;color:#8E8292;margin-top:10px"><span class="kbd">j</span> <span class="kbd">k</span> next patient · <span class="kbd">esc</span> close</div>`;
  dr.classList.add("open");dr.querySelector("#dx").onclick=()=>{sel=null;dr.classList.remove("open");draw()}}
 root.querySelector("#d").oninput=e=>{day=+e.target.value;draw()};
 let raf=null;root.querySelector("#play").onclick=()=>{cancelAnimationFrame(raf);const t0=performance.now();
  const st=t=>{day=Math.min(56,Math.round((t-t0)/6000*56));root.querySelector("#d").value=day;draw();if(day<56)raf=requestAnimationFrame(st)};raf=requestAnimationFrame(st)};
 const vis=()=>P.map((p,i)=>i).filter(i=>{const s=state(P[i],day);return (lane==="all"||lane===s.lane)&&(spec==="all"||spec===P[i].spec)}).sort((a,b)=>state(P[a],day).run-state(P[b],day).run);
 const onKey=e=>{if(!root.isConnected){document.removeEventListener("keydown",onKey);return}if(sel===null)return;
  if(e.key==="Escape"){sel=null;dr.classList.remove("open");draw()}const v=vis(),k=v.indexOf(sel);
  if(e.key==="j"&&k<v.length-1){sel=v[k+1];draw()}if(e.key==="k"&&k>0){sel=v[k-1];draw()}};
 document.addEventListener("keydown",onKey);draw();
 return ()=>{document.removeEventListener("keydown",onKey);cancelAnimationFrame(raf)};
}
"""

_component = st.components.v2.component("authops_coverage_board", css=CSS, js=JS)


def coverage_board(panel, specialty: dict, p90: dict, buffer: int, key: str) -> None:
    pats = [{"pid": p.pid, "spec": p.specialty, "plan": p.plan_type, "end": p.auth_end, "approved": p.units_approved,
             "used": p.units_used, "vpw": round(p.visits_per_week, 3), "covered": p.covered_until,
             "switch": p.switch_day} for p in panel]
    rate = {k: v["rate"] for k, v in specialty.items()}
    upv = {k: v["units_per_visit"] for k, v in specialty.items()}
    leads = [round(p * 7 / 5 + buffer) for p in p90.values()]
    data = {"patients": pats, "rate": rate, "upv": upv, "p90": p90, "buffer": buffer,
            "lead_lo": min(leads), "lead_hi": max(leads),
            "maxrev": max(p.visits_per_week * rate[p.specialty] for p in panel)}
    _component(data=data, key=key)
