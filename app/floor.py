"""Care readiness console (HTML/SVG/JS), fed by authops.sim.floor.build().

A readiness flow (intake -> pre-submission check -> channel -> payor decision), a payor
panel with weekly outcomes, and a patient queue with a detail drawer. Every number is
computed in the browser from real pipeline events, and everything filters everything.
"""
from __future__ import annotations

import json

import streamlit as st

HTML = r"""
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400&family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--ink:#1E0525;--plum:#32073E;--violet:#5B2A86;--lilac:#8C5FB9;--peach:#FFB49D;--pink:#FFCDFF;--rose:#D36E97;
 --sand:#ECE5D8;--line:#F0EAE2;--cream:#FDF8F3;--blush:#FAE8E8;--muted:#8E8292;--soft:#6E5C76}
*{box-sizing:border-box}html,body{margin:0;background:transparent;font-family:'DM Sans',system-ui,sans-serif;color:var(--ink);font-size:14px}
.wrap{position:relative;background:#fff;border:1px solid var(--sand);border-radius:20px;overflow:hidden}
.eyebrow{font:500 11px 'DM Sans';letter-spacing:.13em;text-transform:uppercase;color:var(--muted)}
.serif{font-family:Fraunces,Georgia,serif;font-weight:400;letter-spacing:-.02em}
/* header */
.hd{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;padding:22px 26px 16px;flex-wrap:wrap;
 background:linear-gradient(180deg,#fff, #FDF8F3)}
.hd h2{margin:6px 0 0;font-size:30px;line-height:1.1}
.hd h2 em{font-style:normal;background:linear-gradient(100deg,#E98A6E 0%,#8C5FB9 55%,#C77DC8 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
.time{display:flex;align-items:center;gap:12px;min-width:min(340px,100%);flex:1;max-width:520px}
@media(max-width:560px){.wkl{display:none}.hd h2{font-size:24px}.search{min-width:0;flex:1}}
.time input{flex:1;accent-color:var(--lilac)}
.btn{border:0;background:var(--ink);color:#fff;font:600 13px 'DM Sans';padding:9px 16px;border-radius:999px;cursor:pointer;white-space:nowrap}
.btn:hover{background:var(--plum)}.btn.ghost{background:#fff;color:var(--ink);border:1px solid var(--sand)}.btn.ghost:hover{background:var(--cream)}
.wkl{font:400 15px Fraunces,Georgia,serif;white-space:nowrap;min-width:84px;text-align:right}
/* kpis */
.kpis{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.kpi{padding:16px 22px;border-right:1px solid var(--line);cursor:pointer;transition:background .15s,transform .25s ease,box-shadow .25s;position:relative;transform-style:preserve-3d;will-change:transform}
.kpi:hover{z-index:2;box-shadow:0 18px 34px -24px rgba(30,5,37,.45);border-radius:14px}
.kpi:last-child{border-right:0}.kpi:hover{background:var(--cream)}.kpi.on{background:#F7F1FB}
.kpi.on:after{content:"";position:absolute;left:0;right:0;bottom:-1px;height:2px;background:var(--lilac)}
.kpi b{display:block;font:400 30px Fraunces,Georgia,serif;letter-spacing:-.02em;font-variant-numeric:tabular-nums;margin-top:4px}
.kpi small{font-size:12.5px;color:var(--soft)}
@media(max-width:820px){.kpis{grid-template-columns:repeat(2,1fr)}.kpi:nth-child(2){border-right:0}.kpi:nth-child(-n+2){border-bottom:1px solid var(--line)}}
/* body grid */
.grid{display:grid;grid-template-columns:minmax(0,1.85fr) minmax(0,1fr);border-bottom:1px solid var(--line)}
@media(max-width:960px){.grid{grid-template-columns:1fr}.pane+.pane{border-left:0!important;border-top:1px solid var(--line)}}
.pane{padding:16px 22px 14px}.pane+.pane{border-left:1px solid var(--line)}
.ph{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}
.ph h3{margin:0;font:400 18px Fraunces,Georgia,serif;letter-spacing:-.01em}
.ph .clear{font-size:12px;color:var(--lilac);cursor:pointer;visibility:hidden}.ph .clear.show{visibility:visible}
svg text{font-family:'DM Sans',sans-serif}
.stage3d{perspective:1400px}.stage3d svg{transform:rotateX(var(--rx,7deg)) rotateY(var(--ry,0deg));transform-origin:50% 60%;transition:transform .35s ease-out;
 filter:drop-shadow(0 22px 22px rgba(30,5,37,.10))}
.link{mix-blend-mode:multiply}.dot{pointer-events:none}
.node rect{cursor:pointer;transition:opacity .2s}.link{cursor:pointer;transition:opacity .2s,d .5s ease}
.nlab{font-size:11.5px;fill:var(--ink);font-weight:600;pointer-events:none}.nval{font-size:11px;fill:var(--soft);pointer-events:none}
.stage{font-size:10px;letter-spacing:.12em;fill:var(--muted);text-transform:uppercase;font-weight:500}
/* payors */
.prow{display:grid;grid-template-columns:44px 1fr 54px;align-items:center;gap:10px;padding:7px 8px;border-radius:12px;cursor:pointer;transition:background .15s,transform .2s,box-shadow .2s}
.prow:hover{transform:translateY(-2px);box-shadow:0 12px 22px -18px rgba(30,5,37,.5)}
.spark i span{animation:grow .6s cubic-bezier(.2,.8,.2,1) both}@keyframes grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}.spark i{transform-origin:bottom}
.prow:hover{background:var(--cream)}.prow.on{background:#F7F1FB}
.pcode{font:700 12px 'DM Sans';letter-spacing:.04em}.pname{font-size:11px;color:var(--muted);margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.prate{text-align:right;font:400 17px Fraunces,Georgia,serif}.prate small{display:block;font:500 10px 'DM Sans';color:var(--muted);letter-spacing:.06em}
.spark{display:flex;align-items:flex-end;gap:2px;height:30px;position:relative}
.spark i{flex:1;display:flex;flex-direction:column-reverse;height:100%;border-radius:2px;overflow:hidden;background:#F7F3EE}
.spark i span{display:block;width:100%;transition:height .4s}
.spark i.future{opacity:.35}
.notice{margin:10px 4px 0;border-left:3px solid var(--lilac);background:#F7F1FB;border-radius:0 12px 12px 0;padding:10px 12px;font-size:12.5px;line-height:1.45;cursor:pointer;display:none}
.notice.show{display:block;animation:fi .5s ease}.notice b{font-weight:600}
@keyframes fi{from{opacity:0;transform:translateY(4px)}}
/* queue */
.qbar{display:flex;align-items:center;gap:8px;padding:14px 22px 10px;flex-wrap:wrap}
.qbar h3{margin:0 12px 0 0;font:400 18px Fraunces,Georgia,serif}
.chip{font:500 12px 'DM Sans';border:1px solid var(--sand);background:#fff;color:var(--ink);border-radius:999px;padding:5px 11px;cursor:pointer}
.chip.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.chip.filter{background:#F7F1FB;border-color:#E3D6F2;color:var(--violet)}
.search{margin-left:auto;border:1px solid var(--sand);border-radius:999px;padding:7px 12px;font:13px 'DM Sans';min-width:200px;outline:none}
.search:focus{border-color:var(--lilac)}
.tbl{max-height:330px;overflow:auto;border-top:1px solid var(--line)}
table{width:100%;border-collapse:collapse}
th{position:sticky;top:0;background:#fff;text-align:left;font:500 10.5px 'DM Sans';letter-spacing:.1em;text-transform:uppercase;color:var(--muted);
 padding:10px 14px;border-bottom:1px solid var(--line);cursor:pointer;white-space:nowrap}
th:first-child,td:first-child{padding-left:22px}
td{padding:10px 14px;border-bottom:1px solid var(--line);white-space:nowrap;font-size:13px}
tr.r{cursor:pointer;transition:background .12s}tr.r:hover{background:var(--cream)}tr.r.sel{background:#F7F1FB}
.pill{display:inline-flex;align-items:center;gap:6px;font:600 11.5px 'DM Sans';padding:3px 9px;border-radius:999px}
.pill:before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.p-clear{background:#EFE7FA;color:#5B2A86}.p-partial{background:#F4EDFB;color:#7B57A8}.p-held{background:#FFF1EA;color:#B4532F}
.p-rule{background:#EEE6F2;color:#32073E}.p-denied{background:#FBEAF1;color:#A8355F}
.mut{color:var(--muted)}
/* drawer */
.drawer{position:absolute;top:0;right:0;bottom:0;width:360px;max-width:92%;background:#fff;border-left:1px solid var(--sand);
 box-shadow:-24px 0 48px -30px rgba(30,5,37,.35);transform:translateX(105%);transition:transform .35s cubic-bezier(.2,.8,.2,1);z-index:5;
 padding:22px 22px;overflow:auto}
.drawer.open{transform:none}.drawer .x{position:absolute;right:18px;top:16px;cursor:pointer;color:var(--muted);font-size:16px}
.drawer h3{margin:6px 0 2px;font:400 26px Fraunces,Georgia,serif;letter-spacing:-.02em}
.kv{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin:16px 0;padding:12px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.kv div{font:400 20px Fraunces,Georgia,serif}.kv span{display:block;font:500 10px 'DM Sans';letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:3px}
.tl{position:relative;margin:6px 0 0 6px;padding-left:18px;border-left:1.5px solid var(--sand)}
.ev{position:relative;padding:0 0 14px;animation:evin .4s ease both}@keyframes evin{from{opacity:0;transform:translateX(10px)}}.ev:before{content:"";position:absolute;left:-24.5px;top:3px;width:10px;height:10px;border-radius:50%;background:#fff;border:2px solid var(--lilac)}
.ev.stop:before{border-color:#E0855F;background:#E0855F}.ev.bad:before{border-color:var(--rose);background:var(--rose)}.ev.ok:before{background:var(--lilac)}
.ev b{display:block;font-weight:600;font-size:13px}.ev span{font-size:12px;color:var(--soft)}
.why{margin-top:6px;background:var(--cream);border-radius:12px;padding:12px 14px;font-size:12.5px;line-height:1.5}
#tip{position:fixed;pointer-events:none;background:#fff;border:1px solid var(--sand);border-radius:10px;padding:7px 10px;font-size:12px;
 box-shadow:0 10px 24px -14px rgba(30,5,37,.4);display:none;z-index:9;white-space:nowrap}
</style>
<div class="wrap" id="wrap">
 <div class="hd">
  <div><div class="eyebrow" id="eb">Care readiness · 26 weeks</div><h2 class="serif" id="headline"></h2></div>
  <div class="time"><button class="btn" id="play">Replay 26 weeks</button><input type="range" id="slider" min="1" max="26" step="1" value="26"><div class="wkl" id="wkl">Week 26</div></div>
 </div>
 <div class="kpis" id="kpis"></div>
 <div class="grid">
  <div class="pane"><div class="ph"><h3>Readiness flow</h3><span class="clear" id="clearFlow">Clear selection</span></div><div style="overflow-x:auto" class="stage3d" id="stage"><svg id="flow" width="100%" height="340" style="min-width:560px"></svg></div></div>
  <div class="pane"><div class="ph"><h3>Payors</h3><span class="eyebrow">First-pass approval</span></div><div id="payors"></div><div class="notice" id="notice"></div></div>
 </div>
 <div class="qbar"><h3>Patient queue</h3><span id="chips"></span><input class="search" id="q" placeholder="Search patients, payors, reasons"></div>
 <div class="tbl"><table><thead><tr id="thead"></tr></thead><tbody id="rows"></tbody></table></div>
 <div class="drawer" id="drawer"></div>
</div>
<div id="tip"></div>
<script>
const D=__DATA__, E=D.events, A=D.alert, W=26;
const PAYORS=["NWH","KCM","SFB","HBL","PRV"], NAMES={};E.forEach(e=>NAMES[e.payor]=e.payor_name);
const SPEC={aba:["ABA","hours"],physical_therapy:["Physical therapy","visits"],behavioral_health:["Behavioral health","sessions"]};
const CH={portal:"Portal agent",fhir:"FHIR API",phone:"Phone agent"};
const SHORT=[[/signed/,"Unsigned plan","doc"],[/ICD-10/,"Invalid ICD-10","doc"],[/Plan period/,"Plan expired","doc"],[/CPT/,"CPT ≠ specialty","doc"],
 [/New rule/,"Over new visit cap","rule"],[/per-request limit/,"Over unit limit","rule"],[/school/,"Needs school schedule","rule"],
 [/Medical necessity/,"Medical necessity","x"],[/limited to 20/,"Over visit cap","x"]];
const why=r=>{for(const s of SHORT)if(s[0].test(r||""))return s;return [null,"Other","doc"]};
E.forEach(e=>{e.c=e.outcome==="approved"?"clear":e.outcome==="partial"?"partial":e.outcome==="denied"?"denied":e.learned?"rule":"held";
 e.hold=e.outcome==="caught"?(why(e.reason)[2]==="rule"?"Held: payor rule":"Held: documents"):"Ready to submit";
 e.dec=e.c==="clear"?"Approved in full":e.c==="partial"?"Partially approved":e.c==="denied"?"Denied":null;
 e.wk=e.week+1;e.status=e.c==="clear"?"Clear for care":e.c==="partial"?"Partial approval":e.c==="denied"?"Denied · "+(e.next==="appeal"?"appeal":"resubmit"):"Held · "+why(e.reason)[1]});
let week=26, playing=null, F={node:null,payor:null,kpi:null,spec:"all",q:""}, sortK="wk", sortDir=-1, sel=null;
const $=id=>document.getElementById(id), tip=$("tip");
const showTip=(ev,h)=>{tip.innerHTML=h;tip.style.display="block";tip.style.left=(ev.clientX+14)+"px";tip.style.top=(ev.clientY+12)+"px"},hideTip=()=>tip.style.display="none";
const inTime=e=>e.wk<=week;
const passNode=e=>{const n=F.node;if(!n)return true;const [st,v]=n;return st===0?e.src===v:st===1?e.hold===v:st===2?(e.outcome!=="caught"&&CH[e.channel]===v):e.dec===v};
const KPIF={clear:e=>e.c==="clear"||e.c==="partial",held:e=>e.c==="held"||e.c==="rule",rule:e=>e.c==="rule",fp:e=>e.outcome!=="caught"};
const base=e=>inTime(e)&&(F.spec==="all"||e.spec===F.spec);
const filt=e=>base(e)&&passNode(e)&&(!F.payor||e.payor===F.payor)&&(!F.kpi||KPIF[F.kpi](e))&&
 (!F.q||(e.name+" "+e.payor_name+" "+e.status+" "+e.id).toLowerCase().includes(F.q));
// ---------------------------------------------------------------- header + kpis
function drawHead(){const L=E.filter(e=>base(e)&&(!F.payor||e.payor===F.payor));const clr=L.filter(KPIF.clear).length;
 $("headline").innerHTML=`${L.length} patients, <em>${clr} clear for care</em>`;
 $("eb").textContent=`Care readiness · ${F.payor?NAMES[F.payor]:"all payors"} · through week ${week}`;
 const sub=L.filter(KPIF.fp),fp=sub.length?Math.round(100*sub.filter(e=>e.c==="clear").length/sub.length):0;
 const K=[["clear",clr,"Clear for care",""],["held",L.filter(KPIF.held).length,"Fixed before payor",""],
  ["fp",fp,"First-pass approval","%"],["rule",L.filter(KPIF.rule).length,"Saved by a learned rule",""]];
 if(!$("kpis").children.length){$("kpis").innerHTML=K.map(([k,,l])=>`<div class="kpi" data-k="${k}"><div class="eyebrow">${l}</div><b>0</b></div>`).join("");
  $("kpis").querySelectorAll(".kpi").forEach(d=>{d.onclick=()=>{F.kpi=F.kpi===d.dataset.k?null:d.dataset.k;all()};
   d.onmousemove=ev=>{const r=d.getBoundingClientRect(),x=(ev.clientX-r.left)/r.width-.5,y=(ev.clientY-r.top)/r.height-.5;
    d.style.transform=`perspective(700px) rotateX(${-y*10}deg) rotateY(${x*12}deg) translateZ(8px)`};d.onmouseleave=()=>d.style.transform=""})}
 K.forEach(([k,v,,suf],i)=>{const d=$("kpis").children[i];d.classList.toggle("on",F.kpi===k);countTo(d.querySelector("b"),v,suf)});
 }
function countTo(el,v,suf){const from=+(el.dataset.v||0);el.dataset.v=v;if(from===v){el.textContent=v+suf;return}const t0=performance.now();cancelAnimationFrame(el._r);
 const step=t=>{const k=Math.min(1,(t-t0)/650),e=1-Math.pow(1-k,3);el.textContent=Math.round(from+(v-from)*e)+suf;if(k<1)el._r=requestAnimationFrame(step)};el._r=requestAnimationFrame(step)}
// ---------------------------------------------------------------- flow (sankey)
const STAGES=[["Intake",["Fax","EHR","Upload"]],["Readiness check",["Ready to submit","Held: documents","Held: payor rule"]],
 ["Channel",["Portal agent","FHIR API","Phone agent"]],["Payor decision",["Approved in full","Partially approved","Denied"]]];
const NCOL={"Fax":"#F2A98F","EHR":"#E99A85","Upload":"#DE8C83","Ready to submit":"#A57BD0","Held: documents":"#EE9A7C","Held: payor rule":"#32073E",
 "Portal agent":"#9A6FC8","FHIR API":"#8C5FB9","Phone agent":"#7E52AE","Approved in full":"#5B2A86","Partially approved":"#B99BE0","Denied":"#D36E97"};
const key=(e,s)=>s===0?e.src:s===1?e.hold:s===2?(e.outcome==="caught"?null:CH[e.channel]):e.dec;
function drawFlow(){const svg=$("flow"),Wd=svg.clientWidth||700,H=340,top=26,bot=8,nw=12,gap=10;
 const L=E.filter(e=>base(e)&&(!F.payor||e.payor===F.payor)&&(!F.kpi||KPIF[F.kpi](e)));const tot=Math.max(1,L.length);
 const usable=H-top-bot-gap*2-34,scale=usable/tot,xs=STAGES.map((_,i)=>4+i*(Wd-nw-168)/(STAGES.length-1));
 const nodes={};STAGES.forEach(([_,names],s)=>{let y=top;names.forEach(n=>{const v=L.filter(e=>key(e,s)===n).length,h=Math.max(v?2:0,v*scale);
  nodes[s+"|"+n]={s,n,v,x:xs[s],y,h,out:y,in:y};y+=Math.max(h,v?16:0)+(v?gap:0)})});
 let links=[];for(let s=0;s<3;s++){const pairs={};L.forEach(e=>{const a=key(e,s),b=key(e,s+1);if(a&&b){const k=a+"→"+b;(pairs[k]=pairs[k]||{a,b,v:0,ids:[]}).v++;pairs[k].ids.push(e.id)}});
  Object.values(pairs).sort((p,q)=>STAGES[s+1][1].indexOf(p.b)-STAGES[s+1][1].indexOf(q.b)).forEach(p=>{const A_=nodes[s+"|"+p.a],B=nodes[(s+1)+"|"+p.b],h=p.v*scale;
   links.push({s,a:p.a,b:p.b,v:p.v,h,x0:A_.x+nw,y0:A_.out,x1:B.x,y1:B.in});A_.out+=h;B.in+=h})}
 const act=F.node?F.node[0]+"|"+F.node[1]:null;
 const lit=l=>!act||(F.node[0]===l.s&&F.node[1]===l.a)||(F.node[0]===l.s+1&&F.node[1]===l.b)||L.some(e=>passNode(e)&&key(e,l.s)===l.a&&key(e,l.s+1)===l.b);
 let s=`<defs>${links.map((l,i)=>`<linearGradient id="g${i}" x1="0" x2="1"><stop offset="0" stop-color="${NCOL[l.a]}"/><stop offset="1" stop-color="${NCOL[l.b]}"/></linearGradient>`).join("")}</defs>`;
 STAGES.forEach(([n],i)=>s+=`<text class="stage" x="${xs[i]}" y="12">${n}</text>`);
 links.forEach((l,i)=>{const mx=(l.x0+l.x1)/2;const d=`M${l.x0},${l.y0} C${mx},${l.y0} ${mx},${l.y1} ${l.x1},${l.y1} L${l.x1},${l.y1+l.h} C${mx},${l.y1+l.h} ${mx},${l.y0+l.h} ${l.x0},${l.y0+l.h} Z`;
  s+=`<path class="link" data-i="${i}" d="${d}" fill="url(#g${i})" opacity="${lit(l)?.42:.08}"/>`});
 s+=`<g id="dots"></g>`;
 Object.values(nodes).forEach(n=>{if(!n.v)return;const on=!act||act===n.s+"|"+n.n;
  s+=`<g class="node" data-k="${n.s}|${n.n}" opacity="${on?1:.3}"><path d="M${n.x+nw},${n.y} l5,-4 v${n.h} l-5,4 Z" fill="${NCOL[n.n]}" style="filter:brightness(.72)"/>
   <path d="M${n.x},${n.y} l5,-4 h${nw} l-5,4 Z" fill="${NCOL[n.n]}" style="filter:brightness(1.18)"/><rect x="${n.x}" y="${n.y}" width="${nw}" height="${n.h}" rx="1.5" fill="${NCOL[n.n]}"/>
   ${n.h>=28?`<text class="nlab" x="${n.x+nw+7}" y="${n.y+14}">${n.n}</text><text class="nval" x="${n.x+nw+7}" y="${n.y+27}">${n.v} · ${Math.round(100*n.v/tot)}%</text>`
    :`<text class="nlab" x="${n.x+nw+7}" y="${n.y+n.h/2+4}">${n.n} <tspan class="nval">${n.v} · ${Math.round(100*n.v/tot)}%</tspan></text>`}</g>`});
 if(!L.length)s+=`<text x="${Wd/2}" y="${H/2}" text-anchor="middle" class="nval">No patients match these filters yet.</text>`;
 svg.innerHTML=s;
 DOTS=[];links.forEach((l,i)=>{const n=Math.min(14,Math.ceil(l.v/5));for(let k=0;k<n;k++)DOTS.push({l,lit:lit(l),t:Math.random(),off:.15+Math.random()*.7,sp:.00018+Math.random()*.00014})});
 const g=svg.querySelector("#dots");g.innerHTML=DOTS.map(d=>`<circle class="dot" r="${d.lit?2.1:1.4}" fill="#fff" opacity="${d.lit?.95:.35}"/>`).join("");DOTEL=[...g.children];
 svg.querySelectorAll(".link").forEach(p=>{const l=links[+p.dataset.i];p.onmousemove=ev=>{p.setAttribute("opacity",.75);showTip(ev,`<b>${l.a}</b> → <b>${l.b}</b> · ${l.v} patients`)};
  p.onmouseleave=()=>{p.setAttribute("opacity",lit(l)?.42:.08);hideTip()}});
 svg.querySelectorAll(".node").forEach(g=>{const [st,...n]=g.dataset.k.split("|"),nm=n.join("|");g.onclick=()=>{F.node=act===g.dataset.k?null:[+st,nm];all()};
  g.onmousemove=ev=>showTip(ev,`Click to filter the queue to <b>${nm}</b>`);g.onmouseleave=hideTip});
 $("clearFlow").classList.toggle("show",!!F.node);$("clearFlow").onclick=()=>{F.node=null;all()}}
let DOTS=[],DOTEL=[],lastT=performance.now();
const bz=(a,b,c,d,t)=>{const u=1-t;return u*u*u*a+3*u*u*t*b+3*u*t*t*c+t*t*t*d};
function animate(t){const dt=Math.min(50,t-lastT);lastT=t;DOTS.forEach((d,i)=>{d.t=(d.t+d.sp*dt)%1;const l=d.l,mx=(l.x0+l.x1)/2;
  const x=bz(l.x0,mx,mx,l.x1,d.t),y=bz(l.y0,l.y0,l.y1,l.y1,d.t)+d.off*l.h;const c=DOTEL[i];if(c){c.setAttribute("cx",x);c.setAttribute("cy",y)}});requestAnimationFrame(animate)}
requestAnimationFrame(animate);
const STG=document.getElementById("stage");
STG.onmousemove=ev=>{const r=STG.getBoundingClientRect(),x=(ev.clientX-r.left)/r.width-.5,y=(ev.clientY-r.top)/r.height-.5;
 STG.style.setProperty("--ry",(x*7)+"deg");STG.style.setProperty("--rx",(7-y*7)+"deg")};
STG.onmouseleave=()=>{STG.style.setProperty("--ry","0deg");STG.style.setProperty("--rx","7deg")};
// ---------------------------------------------------------------- payors
function drawPayors(){const P=$("payors");P.innerHTML=PAYORS.map(p=>{const L=E.filter(e=>e.payor===p&&base(e)),sub=L.filter(KPIF.fp);
  const fp=sub.length?Math.round(100*sub.filter(e=>e.c==="clear").length/sub.length):0;
  const bars=[...Array(W)].map((_,w)=>{const B=E.filter(e=>e.payor===p&&e.wk===w+1&&(F.spec==="all"||e.spec===F.spec)),n=Math.max(1,6);
   const seg=(k,c)=>{const v=B.filter(k).length;return v?`<span style="height:${Math.min(100,v/n*100)}%;background:${c}"></span>`:""};
   return `<i class="${w+1>week?"future":""}" data-w="${w+1}" data-p="${p}">${seg(e=>e.c==="clear"||e.c==="partial","#8C5FB9")}${seg(e=>e.c==="held"||e.c==="rule","#F2A98F")}${seg(e=>e.c==="denied","#D36E97")}</i>`}).join("");
  return `<div class="prow ${F.payor===p?"on":""}" data-p="${p}"><div><div class="pcode">${p}</div></div><div><div class="spark">${bars}</div><div class="pname">${NAMES[p]}</div></div>
   <div class="prate">${fp}%<small>${sub.length} SENT</small></div></div>`}).join("");
 P.querySelectorAll(".prow").forEach(r=>r.onclick=()=>{F.payor=F.payor===r.dataset.p?null:r.dataset.p;all()});
 P.querySelectorAll(".spark i").forEach(b=>{b.onmousemove=ev=>{const w=+b.dataset.w,B=E.filter(e=>e.payor===b.dataset.p&&e.wk===w&&(F.spec==="all"||e.spec===F.spec));
  showTip(ev,`<b>${b.dataset.p} · week ${w}</b><br>${B.filter(e=>e.c==="clear"||e.c==="partial").length} clear · ${B.filter(e=>e.c==="held"||e.c==="rule").length} fixed before payor · ${B.filter(e=>e.c==="denied").length} denied`)};b.onmouseleave=hideTip});
 const n=$("notice");if(week>A.week+1){n.innerHTML=`<b>New payor rule · week ${A.week+1}</b><br>${A.payor} caps physical therapy at 20 visits. Learned from denials, enforced from week ${A.week+2}. <u>Show who it saved</u>`;
  n.classList.add("show");n.onclick=()=>{F.payor=A.payor;F.kpi="rule";F.node=null;all()}}else n.classList.remove("show")}
// ---------------------------------------------------------------- queue
const COLS=[["name","Patient"],["spec","Service"],["payor","Payor"],["src","Source"],["status","Status"],["units","Requested"],["recommended","Submitted"],["approved","Approved"],["wk","Week"]];
function drawQueue(){$("thead").innerHTML=COLS.map(([k,l])=>`<th data-k="${k}">${l}${sortK===k?(sortDir>0?" ↑":" ↓"):""}</th>`).join("");
 $("thead").querySelectorAll("th").forEach(t=>t.onclick=()=>{sortDir=sortK===t.dataset.k?-sortDir:1;sortK=t.dataset.k;drawQueue()});
 const L=E.filter(filt).sort((a,b)=>{const x=a[sortK]??-1,y=b[sortK]??-1;return (x>y?1:x<y?-1:0)*sortDir});
 const u=e=>SPEC[e.spec][1];
 $("rows").innerHTML=L.map(e=>`<tr class="r ${sel===e?"sel":""}" data-id="${e.id}"><td><b style="font-weight:600">${e.name}</b><div class="mut" style="font-size:11px">${e.id}</div></td>
  <td>${SPEC[e.spec][0]}</td><td>${e.payor}</td><td>${e.src}</td><td><span class="pill p-${e.c}">${e.status}</span></td>
  <td>${e.units} <span class="mut">${u(e)}</span></td><td>${e.recommended??'<span class="mut">not sent</span>'}</td><td>${e.approved??'<span class="mut">–</span>'}</td><td>${e.wk}</td></tr>`).join("")
  ||`<tr><td colspan="9" class="mut" style="padding:22px">No patients match these filters.</td></tr>`;
 $("rows").querySelectorAll("tr.r").forEach(r=>r.onclick=()=>openDrawer(E.find(e=>e.id===r.dataset.id)));
 const chips=[];if(F.node)chips.push([F.node[1],()=>F.node=null]);if(F.payor)chips.push([NAMES[F.payor],()=>F.payor=null]);
 if(F.kpi)chips.push([{clear:"Clear for care",held:"Fixed before payor",fp:"Submitted",rule:"Learned rule"}[F.kpi],()=>F.kpi=null]);
 $("chips").innerHTML=["all","aba","physical_therapy","behavioral_health"].map(s=>`<button class="chip ${F.spec===s?"on":""}" data-s="${s}">${s==="all"?"All services":SPEC[s][0]}</button>`).join(" ")
  +" "+chips.map((c,i)=>`<button class="chip filter" data-c="${i}">${c[0]} ✕</button>`).join(" ")+` <span class="mut" style="font-size:12px;margin-left:6px">${L.length} shown</span>`;
 $("chips").querySelectorAll("[data-s]").forEach(b=>b.onclick=()=>{F.spec=b.dataset.s;all()});
 $("chips").querySelectorAll("[data-c]").forEach(b=>b.onclick=()=>{chips[+b.dataset.c][1]();all()})}
$("q").oninput=ev=>{F.q=ev.target.value.trim().toLowerCase();drawQueue()};
// ---------------------------------------------------------------- drawer
function openDrawer(e){sel=e;const u=SPEC[e.spec][1],dr=$("drawer");
 const ev=[["ok",`Received via ${e.src==='Upload'?'upload':e.src==='Fax'?'fax':'EHR'}`,`Week ${e.wk}`],["ok","Benefits verified","Coverage, visit limits and auth requirement checked"],["ok","Documents read","Treatment plan fields extracted and validated"]];
 if(e.outcome==="caught")ev.push(["stop","Held at pre-submission check",why(e.reason)[1]+(e.learned?" · rule learned from denials":"")]);
 else{ev.push(["ok","Pre-submission check passed",e.qa?"Reviewed by a human before sending":"No human review needed"]);
  ev.push(["ok",`Submitted through ${CH[e.channel].toLowerCase()}`,`${e.recommended} ${u} requested`]);
  ev.push([e.c==="denied"?"bad":"ok",e.c==="denied"?"Denied by payor":e.c==="partial"?"Partially approved":"Approved in full",e.approved!=null?`${e.approved} ${u} approved`:""]);
  if(e.c!=="denied")ev.push(["ok","Clear for care",""]);else ev.push(["bad",e.next==="appeal"?"Appeal packet drafted":"Corrected and queued to resubmit",""])}
 const note=e.c==="held"?`Stopped before the payor saw it: ${e.reason}`:e.c==="rule"?`${e.reason} Before this rule existed, requests like this were sent and denied.`
  :e.c==="denied"?`${e.reason} ${e.next==="appeal"?"The appeal cites the chart page by page.":"The plan is corrected before resubmitting."}`
  :e.c==="partial"?`The clinic asked for ${e.units} ${u}. AuthOps requested ${e.recommended}; the payor approved ${e.approved}. Reauthorization is scheduled before the visits run out.`
  :e.recommended<e.units?`The clinic asked for ${e.units} ${u}. AuthOps requested ${e.recommended}, the amount this payor approves in full, so care starts on the first pass.`:"Approved in full on the first pass.";
 dr.innerHTML=`<span class="x" id="dx">✕</span><div class="eyebrow">${e.id} · ${SPEC[e.spec][0]}</div><h3>${e.name}</h3>
  <div class="mut" style="font-size:13px">${e.payor_name}</div><div style="margin-top:10px"><span class="pill p-${e.c}">${e.status}</span></div>
  <div class="kv"><div><span>Requested</span>${e.units}</div><div><span>Submitted</span>${e.recommended??"–"}</div><div><span>Approved</span>${e.approved??"–"}</div></div>
  <div class="eyebrow" style="margin-bottom:10px">Timeline</div><div class="tl">${ev.map(([k,b,s],i)=>`<div class="ev ${k}" style="animation-delay:${120+i*90}ms"><b>${b}</b><span>${s}</span></div>`).join("")}</div>
  <div class="why">${note}</div>`;
 dr.classList.add("open");$("dx").onclick=()=>{dr.classList.remove("open");sel=null;drawQueue()};drawQueue()}
// ---------------------------------------------------------------- time
function all(){drawHead();drawFlow();drawPayors();drawQueue()}
$("slider").oninput=ev=>{week=+ev.target.value;$("wkl").textContent="Week "+week;stop();all()};
function stop(){if(playing){clearInterval(playing);playing=null;$("play").textContent="Replay 26 weeks"}}
$("play").onclick=()=>{if(playing){stop();return}week=1;F.node=null;F.kpi=null;F.payor=null;$("play").textContent="Pause";
 playing=setInterval(()=>{week++;$("slider").value=week;$("wkl").textContent="Week "+week;all();if(week>=W)stop()},700);all()};
window.addEventListener("resize",drawFlow);all();
</script>
"""


def operations_floor(data: dict) -> None:
    st.iframe(HTML.replace("__DATA__", json.dumps(data)), height="content")
