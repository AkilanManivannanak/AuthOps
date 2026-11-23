"""Care departures board (HTML/SVG/JS), fed by authops.sim.floor.build().

Every patient waiting on a prior auth is a departure: the board flips each request
through the real pipeline stages, the timeline below scrubs 26 weeks, and a care
pass opens for any patient. All rows are events produced by the actual pipeline.
"""
from __future__ import annotations

import json

import streamlit as st

HTML = r"""
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@500;700&family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root{--board:#14211B;--board2:#1B2C24;--cream:#F3EBD3;--dim:#7E8F85;--green:#58C08A;--amber:#F0B44C;
--red:#EF6F5E;--violet:#B79CFF;--ink:#1F2A24;--paper:#FBF9F4;--rule:#E5E0D4}
*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,sans-serif;color:var(--ink);background:transparent}
.wrap{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:14px}
@media(max-width:900px){.wrap{grid-template-columns:1fr}}
.board{background:var(--board);border-radius:18px;padding:14px 14px 10px;color:var(--cream);
  box-shadow:0 12px 30px -18px rgba(0,0,0,.5);position:relative;overflow:hidden}
.top{display:flex;justify-content:space-between;align-items:flex-end;gap:10px;flex-wrap:wrap;padding:0 4px 10px;
  border-bottom:1px solid #2A3D33}
.ttl{font:700 12px 'JetBrains Mono',monospace;letter-spacing:.22em;color:var(--amber)}
.wk{font:700 26px 'JetBrains Mono',monospace;letter-spacing:.06em}
.wk small{font-size:12px;color:var(--dim);letter-spacing:.15em;margin-left:6px}
.cnt{display:flex;gap:14px}
.cnt div{text-align:right}.cnt b{display:block;font:700 22px 'JetBrains Mono',monospace}
.cnt span{font:600 9.5px 'JetBrains Mono',monospace;letter-spacing:.14em;color:var(--dim)}
.ribbon{margin:10px 0 2px;padding:8px 12px;border-radius:10px;background:#2A2247;border:1px solid #4B3D86;
  font:600 12.5px Inter;color:#E6DEFF;display:none;cursor:pointer;transform-origin:top}
.ribbon.show{display:block;animation:drop .5s cubic-bezier(.2,1.4,.4,1)}
.ribbon b{font-family:'JetBrains Mono',monospace;color:var(--violet);letter-spacing:.1em;margin-right:6px}
@keyframes drop{from{transform:rotateX(-90deg);opacity:0}to{transform:none;opacity:1}}
table{width:100%;border-collapse:collapse;margin-top:6px;table-layout:fixed}
th{font:600 9.5px 'JetBrains Mono',monospace;letter-spacing:.16em;color:var(--dim);text-align:left;padding:6px 6px}
td{font:500 13px 'JetBrains Mono',monospace;padding:0 6px;height:34px;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;border-top:1px solid #22342B}
tr.row{cursor:pointer;transition:background .2s}tr.row:hover{background:var(--board2)}
tr.row.sel{background:#22382D;box-shadow:inset 3px 0 0 var(--amber)}
tr.row.new{animation:slide .45s ease-out}
@keyframes slide{from{transform:translateY(-14px);opacity:0}to{transform:none;opacity:1}}
.st{font-weight:700;letter-spacing:.03em}
.c-run{color:var(--cream)}.c-ok{color:var(--green)}.c-hold{color:var(--amber)}.c-rule{color:var(--violet)}
.c-bad{color:var(--red)}.c-qa{color:#8FC3FF}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px;vertical-align:1px}
.sub{display:none}
@media(max-width:620px){.hide-s{display:none}td{font-size:11.5px;height:40px}th:first-child{width:44%!important}
 .sub{display:block;font-size:9.5px;color:var(--dim);margin-top:1px}.cnt{gap:10px}.cnt b{font-size:18px}}
.lens{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 0}
.chip{font:600 11.5px Inter;border:1px solid #33493E;color:var(--cream);background:transparent;
  border-radius:999px;padding:5px 11px;cursor:pointer;transition:all .15s}
.chip:hover{border-color:var(--amber)}.chip.on{background:var(--cream);color:var(--board);border-color:var(--cream)}
.chip.rule.on{background:var(--violet);border-color:var(--violet)}
/* timeline */
.tl{margin-top:12px;display:flex;align-items:center;gap:10px}
.play{width:38px;height:38px;border-radius:50%;border:none;background:var(--amber);color:var(--board);
  font-size:15px;cursor:pointer;flex:none;transition:transform .15s}.play:hover{transform:scale(1.08)}
svg.hist{width:100%;height:78px;cursor:ew-resize;touch-action:none;user-select:none}
/* care pass */
.pass{background:var(--paper);border:1px solid var(--rule);border-radius:18px;position:relative;overflow:hidden;
  min-height:420px;display:flex;flex-direction:column}
.pass .hd{background:var(--ink);color:var(--cream);padding:12px 16px;font:700 11px 'JetBrains Mono',monospace;
  letter-spacing:.2em;display:flex;justify-content:space-between}
.pass .bd{padding:14px 16px 16px;flex:1;position:relative}
.pname{font:700 21px Inter;margin:2px 0 10px}
.route{display:flex;align-items:center;justify-content:space-between;margin:6px 0 14px}
.code{font:700 28px 'JetBrains Mono',monospace;letter-spacing:.04em}
.code small{display:block;font:600 9.5px Inter;letter-spacing:.12em;color:#8A8A80;text-transform:uppercase}
.plane{flex:1;margin:0 10px;border-top:2px dashed #CFC7B4;position:relative;height:0}
.plane i{position:absolute;top:-9px;font-style:normal;font-size:14px;transition:left .6s}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px;font-size:12.5px}
.grid2 span{display:block;font:600 9.5px Inter;letter-spacing:.12em;color:#8A8A80;text-transform:uppercase}
.perf{border-top:2px dashed var(--rule);margin:14px -16px 12px;position:relative}
.perf:before,.perf:after{content:"";position:absolute;top:-9px;width:16px;height:16px;border-radius:50%;
  background:#fff;border:1px solid var(--rule)}.perf:before{left:-9px}.perf:after{right:-9px}
.steps{display:flex;gap:4px;margin-bottom:10px}
.step{flex:1;text-align:center;font:600 8.5px Inter;letter-spacing:.08em;color:#9A9A90;text-transform:uppercase}
.step i{display:block;width:22px;height:22px;margin:0 auto 4px;border-radius:50%;border:2px solid #D8D2C2;
  transition:all .3s}
.step.done i{background:var(--ink);border-color:var(--ink)}.step.done{color:var(--ink)}
.step.hold i{background:#E7A93B;border-color:#E7A93B}.step.bad i{background:#C9513F;border-color:#C9513F}
.why{font-size:12.5px;line-height:1.45;color:#3A3A36;min-height:36px}
.stamp{position:absolute;right:16px;bottom:44px;font:700 15px 'JetBrains Mono',monospace;letter-spacing:.14em;
  padding:6px 10px;border:3px solid;border-radius:8px;transform:rotate(-12deg) scale(1);opacity:.85}
.stamp.pop{animation:stamp .35s cubic-bezier(.3,1.8,.5,1)}
@keyframes stamp{from{transform:rotate(-12deg) scale(2.2);opacity:0}}
.live{font:600 10px Inter;color:#8A8A80;margin-top:10px}
.live b{color:var(--ink);cursor:pointer;text-decoration:underline}
</style>
<div class="wrap">
 <div class="board">
  <div class="top">
   <div><div class="ttl">CARE DEPARTURES</div><div class="wk" id="wk">WK 01<small>/ 26</small></div></div>
   <div class="cnt">
    <div><b id="k-care" class="c-ok">0</b><span>STARTED CARE</span></div>
    <div><b id="k-held" class="c-hold">0</b><span>HELD, NOT DENIED</span></div>
    <div><b id="k-rule" class="c-rule">0</b><span>NEW-RULE SAVES</span></div>
    <div><b id="k-bad" class="c-bad">0</b><span>DENIED</span></div>
   </div>
  </div>
  <div class="ribbon" id="ribbon"></div>
  <table><thead><tr><th style="width:24%">PATIENT</th><th class="hide-s" style="width:9%">SVC</th><th class="hide-s" style="width:9%">PAYOR</th>
   <th class="hide-s" style="width:10%">VIA</th><th>STATUS</th></tr></thead><tbody id="rows"></tbody></table>
  <div class="lens" id="lens"></div>
  <div class="tl"><button class="play" id="play" title="Play / pause">❚❚</button><svg class="hist" id="hist"></svg></div>
 </div>
 <div class="pass" id="pass"></div>
</div>
<script>
const D=__DATA__, E=D.events, A=D.alert, W=26, ROWS=10, WEEK_MS=1500;
const SPEC={aba:["ABA","hrs"],physical_therapy:["PT","visits"],behavioral_health:["BH","sessions"]};
const VIA={portal:"PORTAL",fhir:"FHIR API",phone:"PHONE"};
const SRC={Fax:"FAX",EHR:"EHR",Upload:"UPLD"};
const SHORT=[[/signed/,"UNSIGNED PLAN"],[/ICD-10/,"BAD ICD-10 CODE"],[/New rule/,"OVER NEW 20-VISIT CAP"],
 [/Plan period/,"PLAN EXPIRED"],[/CPT/,"CPT ≠ SPECIALTY"],[/per-request limit/,"SPLIT: OVER LIMIT"],
 [/school/,"NEEDS SCHOOL SCHEDULE"],[/Medical necessity/,"NECESSITY"],[/limited to 20/,"OVER 20-VISIT CAP"]];
const short=r=>{for(const [rx,s] of SHORT) if(rx.test(r||"")) return s; return "SEE NOTE"};
// place each event inside its week and lay out its stage times (in weeks)
const byWeek={};E.forEach(e=>(byWeek[e.week]=byWeek[e.week]||[]).push(e));
Object.values(byWeek).forEach(L=>L.forEach((e,i)=>{e.t0=e.week+0.8*(i+.5)/L.length}));
E.forEach(e=>{const t=e.t0,s=[[t,(e.src==="Fax"?"FAX RECEIVED":e.src==="EHR"?"PULLED FROM EHR":"UPLOADED"),"run"],
  [t+.1,"READING DOCUMENTS","run"],[t+.22,"CHECKING PAYOR RULES","run"]];
 let k=t+.32; if(e.qa){s.push([k,"HUMAN CHECK","qa"]);k+=.15}
 if(e.outcome==="caught"){s.push([k,"HELD · "+short(e.reason),e.learned?"rule":"hold"]);e.tEnd=k}
 else{s.push([k,"SENT · "+VIA[e.channel],"run"]);const u=SPEC[e.spec][1];k+=.45;
  if(e.outcome==="approved")s.push([k,`CLEARED · ${e.approved} ${u.toUpperCase()}`,"ok"]);
  else if(e.outcome==="partial")s.push([k,`PARTIAL · ${e.approved} OF ${e.recommended}`,"hold"]);
  else{s.push([k,"DENIED · "+short(e.reason),"bad"]);s.push([k+.5,e.next==="appeal"?"APPEAL FILED":"FIX + RESUBMIT","bad"])}
  e.tEnd=k}
 e.stages=s});
const stageAt=(e,c)=>{let cur=e.stages[0];for(const s of e.stages) if(s[0]<=c) cur=s; return cur};
let clock=0, playing=true, sel=null, follow=true, spec="all", lens="all", last=performance.now(), seen=new Set(), ribbonShown=false, shown={};
const $=id=>document.getElementById(id);
const pass=e=>(spec==="all"||e.spec===spec)&&(lens==="all"||(lens==="rule"&&e.learned)||(lens==="held"&&e.outcome==="caught")||(lens==="bad"&&e.outcome==="denied")||(lens===e.payor));
// split-flap: scramble then settle
const CH="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789·";
function flap(el,txt){if(el.dataset.t===txt)return;el.dataset.t=txt;let f=0;const n=7;clearInterval(el._i);
 el._i=setInterval(()=>{f++;el.textContent=txt.split("").map((c,i)=>c===" "||i<txt.length*f/n?c:CH[Math.random()*CH.length|0]).join("");
  if(f>=n){clearInterval(el._i);el.textContent=txt}},32)}
function count(el,v){if(+el.dataset.v!==v){el.dataset.v=v;flap(el,String(v))}}
// lens chips
const chips=[["all","All"],["aba","ABA"],["physical_therapy","PT"],["behavioral_health","BH"]];
const lenses=[["rule","⚑ Saved by the learned rule"],["held","Held before payor"],["bad","Denied"]];
function drawLens(){$("lens").innerHTML=chips.map(c=>`<button class="chip ${spec===c[0]?"on":""}" data-s="${c[0]}">${c[1]}</button>`).join("")
 +'<span style="width:10px"></span>'+lenses.map(c=>`<button class="chip ${c[0]==="rule"?"rule":""} ${lens===c[0]?"on":""}" data-l="${c[0]}">${c[1]}</button>`).join("");
 $("lens").querySelectorAll("[data-s]").forEach(b=>b.onclick=()=>{spec=b.dataset.s;drawLens();drawHist();tick(true)});
 $("lens").querySelectorAll("[data-l]").forEach(b=>b.onclick=()=>{lens=lens===b.dataset.l?"all":b.dataset.l;drawLens();drawHist();tick(true)})}
// timeline histogram
const H=$("hist");
function drawHist(){const w=H.clientWidth||700,h=78,bw=w/W,mx=Math.max(...[...Array(W)].map((_,i)=>E.filter(e=>e.week===i).length));
 let s="";for(let i=0;i<W;i++){const L=E.filter(e=>e.week===i&&pass(e));let y=h-16;
  for(const [k,col] of [["ok","#58C08A"],["hold","#F0B44C"],["rule","#B79CFF"],["bad","#EF6F5E"]]){
   const n=L.filter(e=>(k==="ok"&&(e.outcome==="approved"||e.outcome==="partial"))||(k==="hold"&&e.outcome==="caught"&&!e.learned)||(k==="rule"&&e.learned)||(k==="bad"&&e.outcome==="denied")).length;
   const bh=n/mx*(h-22);y-=bh;s+=`<rect x="${i*bw+1.5}" y="${y}" width="${bw-3}" height="${bh}" rx="1.5" fill="${col}" class="b" data-w="${i}"/>`}}
 const ax=A.week*bw+bw/2;s+=`<line x1="${ax}" x2="${ax}" y1="0" y2="${h-16}" stroke="#B79CFF" stroke-dasharray="3 3"/><text x="${ax+4}" y="9" fill="#B79CFF" font-size="9.5" font-family="JetBrains Mono" font-weight="700">RULE LEARNED</text>`;
 for(let i=0;i<W;i+=5)s+=`<text x="${i*bw+bw/2}" y="${h-3}" fill="#7E8F85" font-size="9" font-family="JetBrains Mono" text-anchor="middle">W${i+1}</text>`;
 s+=`<rect id="shade" x="0" y="0" height="${h-16}" fill="#14211B" opacity=".62"/><line id="head" y1="0" y2="${h-14}" stroke="#F3EBD3" stroke-width="2"/><circle id="knob" r="6" cy="${h-14}" fill="#F3EBD3"/>`;
 H.innerHTML=s;placeHead()}
function placeHead(){const w=H.clientWidth||700,x=Math.min(clock,W)/W*w,sh=H.querySelector("#shade");if(!sh)return;
 sh.setAttribute("x",x);sh.setAttribute("width",Math.max(0,w-x));H.querySelector("#head").setAttribute("x1",x);
 H.querySelector("#head").setAttribute("x2",x);H.querySelector("#knob").setAttribute("cx",x)}
let drag=false;const seek=ev=>{const r=H.getBoundingClientRect();clock=Math.max(0,Math.min(W,(ev.clientX-r.left)/r.width*W));tick(true)};
H.onpointerdown=ev=>{drag=true;H.setPointerCapture(ev.pointerId);setPlay(false);seek(ev)};
H.onpointermove=ev=>{if(drag)seek(ev)};H.onpointerup=()=>drag=false;
function setPlay(p){playing=p;$("play").textContent=p?"❚❚":"▶";last=performance.now()}
$("play").onclick=()=>{if(!playing&&clock>=W+1)clock=0;setPlay(!playing)};
// board
function tick(force){
 const live=E.filter(e=>e.t0<=clock&&pass(e)).sort((a,b)=>b.t0-a.t0).slice(0,ROWS);
 const tb=$("rows");
 if(force||tb.dataset.ids!==live.map(e=>e.id).join()){
  tb.dataset.ids=live.map(e=>e.id).join();
  const keep={};tb.querySelectorAll("tr.row").forEach(tr=>keep[tr.dataset.id]=tr);
  const frag=document.createDocumentFragment();
  live.forEach(e=>{let tr=keep[e.id];
   if(!tr){tr=document.createElement("tr");tr.className="row new";tr.dataset.id=e.id;
    tr.innerHTML=`<td>${e.name}<small class="sub">${SPEC[e.spec][0]} · ${e.payor}</small></td><td class="hide-s">${SPEC[e.spec][0]}</td><td class="hide-s">${e.payor}</td><td class="hide-s">${SRC[e.src]}→${VIA[e.channel].split(" ")[0]}</td><td class="st"></td>`;
    tr.onclick=()=>{sel=e;follow=false;tick(true);drawPass(true)}}
   else tr.classList.remove("new");
   tr.classList.toggle("sel",sel===e);frag.appendChild(tr)});
  for(let i=live.length;i<ROWS;i++){const tr=document.createElement("tr");tr.innerHTML='<td colspan="5"></td>';frag.appendChild(tr)}
  tb.replaceChildren(frag)}
 else tb.querySelectorAll("tr.row").forEach(tr=>tr.classList.toggle("sel",sel&&sel.id===tr.dataset.id));
 tb.querySelectorAll("tr.row").forEach(tr=>{const e=E.find(x=>x.id===tr.dataset.id),[,txt,k]=stageAt(e,clock),td=tr.lastElementChild;
  td.className="st c-"+k;const dc={ok:"#58C08A",hold:"#F0B44C",rule:"#B79CFF",bad:"#EF6F5E",qa:"#8FC3FF",run:"#F3EBD3"}[k];
  if(td.dataset.t!==txt){const prev=shown[e.id];shown[e.id]=txt;td.dataset.t=txt;
   td.innerHTML=`<span class="dot" style="background:${dc}"></span><span></span>`;
   if(prev===txt)td.lastElementChild.textContent=txt;else flap(td.lastElementChild,txt)}});
 const done=E.filter(e=>e.tEnd<=clock&&pass(e));
 count($("k-care"),done.filter(e=>e.outcome==="approved"||e.outcome==="partial").length);
 count($("k-held"),done.filter(e=>e.outcome==="caught").length);
 count($("k-rule"),done.filter(e=>e.learned).length);
 count($("k-bad"),done.filter(e=>e.outcome==="denied").length);
 $("wk").innerHTML=`WK ${String(Math.min(W,Math.floor(clock)+1)).padStart(2,"0")}<small>/ 26</small>`;
 const rb=$("ribbon");
 if(clock>=A.week+.5){if(!rb.classList.contains("show")){rb.innerHTML=`<b>POLICY CHANGE</b>${A.payor} · physical therapy capped at 20 visits per authorization. Learned from denial letters in week ${A.week+1}, enforced from week ${A.week+2}. Click to see who it saved.`;rb.classList.add("show")}}
 else rb.classList.remove("show");
 placeHead();
 if(follow){const n=live[0];if(n&&n!==sel){sel=n;drawPass(true)}}
 drawPass(false)}
$("ribbon").onclick=()=>{lens="rule";drawLens();drawHist();tick(true)};
// care pass
let lastKey="";
function drawPass(force){const e=sel,P=$("pass");
 if(!e){P.innerHTML=`<div class="hd"><span>CARE PASS</span></div><div class="bd"><div class="why">Waiting for the first request…</div></div>`;return}
 const [,txt,k]=stageAt(e,clock),key=e.id+txt;if(!force&&key===lastKey)return;const isNew=e.id!==(lastKey.split("|")[0]);lastKey=e.id+"|"+txt;
 const steps=[["Received",0],["Read",1],["Rules",2]].concat(e.qa?[["Human",3]]:[]).concat(e.outcome==="caught"?[["Held",-1]]:[["Sent",-1],["Decision",-2]]);
 const reached=e.stages.filter(s=>s[0]<=clock).length, final=e.stages[e.stages.length-1];
 const stepHtml=steps.map((s,i)=>{let cls="";if(i<reached)cls="done";
   if(e.outcome==="caught"&&i===steps.length-1)cls=reached>=e.stages.length?"hold":"";
   if(e.outcome==="denied"&&i===steps.length-1&&reached>=e.stages.length-1)cls="bad";return `<div class="step ${cls}"><i></i>${s[0]}</div>`}).join("");
 const ended=clock>=e.tEnd, u=SPEC[e.spec][1];
 const stamp=!ended?"":e.outcome==="approved"?["CLEARED","#2E8B57"]:e.outcome==="partial"?["PARTIAL","#C98B1E"]:e.outcome==="denied"?["DENIED","#C9513F"]:e.learned?["SAVED","#7B5CE0"]:["HELD","#C98B1E"];
 const prog=Math.min(1,(clock-e.t0)/Math.max(.01,e.tEnd-e.t0));
 const units=e.recommended!=null?`<div><span>Clinic asked</span>${e.units} ${u}</div><div><span>AuthOps asked</span>${e.recommended} ${u}</div>
   <div><span>Payor approved</span>${ended?(e.approved??"–")+" "+u:"pending"}</div><div><span>Human check</span>${e.qa?"yes":"no"}</div>`
   :`<div><span>Clinic asked</span>${e.units} ${u}</div><div><span>Human check</span>${e.qa?"yes":"no"}</div>`;
 const why=e.outcome==="caught"?`Stopped before the payor saw it: ${e.reason}`:e.outcome==="denied"?`${e.reason} Next: ${e.next==="appeal"?"appeal packet with chart citations":"fix the plan and resubmit"}.`
   :e.outcome==="partial"?`Payor trimmed the request to ${e.approved} ${u}; reauthorization is scheduled before they run out.`
   :`Asked for what this payor approves in full, so care starts on the first pass.`;
 P.innerHTML=`<div class="hd"><span>CARE PASS</span><span>${e.id}</span></div><div class="bd">
  ${stamp?`<div class="stamp ${isNew||force?"pop":""}" style="color:${stamp[1]};border-color:${stamp[1]}">${stamp[0]}</div>`:""}
  <div style="font:600 10px Inter;letter-spacing:.12em;color:#8A8A80">PATIENT</div><div class="pname">${e.name}</div>
  <div class="route"><div class="code">${SRC[e.src]}<small>${e.src}</small></div><div class="plane"><i style="left:calc(${prog*100}% - 8px)">✈</i></div>
   <div class="code" style="text-align:right">${e.payor}<small>${e.payor_name.split(" ")[0]}</small></div></div>
  <div class="grid2"><div><span>Service</span>${SPEC[e.spec][0]} · ${e.spec.replace("_"," ")}</div><div><span>Channel</span>${VIA[e.channel].toLowerCase()}</div>${units}</div>
  <div class="perf"></div><div class="steps">${stepHtml}</div>
  <div class="why">${ended?why:"In progress: "+txt.toLowerCase()+"."}</div>
  <div class="live">${follow?"Following the newest request. Click any row to pin one.":`Pinned. <b id="unpin">Follow live again</b>`}</div></div>`;
 const up=$("unpin");if(up)up.onclick=()=>{follow=true;tick(true)}}
function loop(now){if(playing){clock+=(now-last)/WEEK_MS;if(clock>=W+1.2){clock=W+1.2;setPlay(false)}}last=now;tick(false);requestAnimationFrame(loop)}
drawLens();drawHist();window.addEventListener("resize",drawHist);requestAnimationFrame(t=>{last=t;loop(t)});
</script>
"""


def operations_floor(data: dict) -> None:
    st.iframe(HTML.replace("__DATA__", json.dumps(data)), height="content")
