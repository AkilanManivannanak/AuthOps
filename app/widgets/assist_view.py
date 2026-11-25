"""Result views for the real-document tools: a letter explained for a patient, a plan checked for a clinic."""
from __future__ import annotations

import streamlit as st

from app.widgets.theme import BASE_CSS

CSS = BASE_CSS + """
.hero{display:grid;grid-template-columns:auto 1fr;gap:22px;align-items:center;padding:22px 24px}
@media(max-width:760px){.hero{grid-template-columns:1fr}}
.stamp{display:inline-block;transform:rotate(-4deg);border:4px solid;border-radius:14px;padding:8px 20px;font:900 24px 'DM Sans',system-ui,sans-serif;
 letter-spacing:.14em;animation:pop .45s cubic-bezier(.3,1.6,.5,1) both;white-space:nowrap}
@keyframes pop{from{transform:rotate(-4deg) scale(1.8);opacity:0}to{transform:rotate(-4deg) scale(1);opacity:1}}
.sum{font:400 21px/1.35 Fraunces,Georgia,serif}
.chips{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}
.chip{border:1px solid var(--sand);border-radius:14px;padding:10px 14px;background:#fff;animation:rise .35s ease both}
.chip b{display:block;font:400 20px Fraunces,Georgia,serif}.chip span{font-size:11px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}
.chip.hot{background:#FBEAF1;border-color:#F4B9CF}.chip.hot b{color:#A8355F}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}@media(max-width:760px){.cols{grid-template-columns:1fr}}
.box{padding:16px 18px}.box h4{margin:0 0 10px;font:400 18px Fraunces,Georgia,serif}
.step{display:flex;gap:12px;align-items:flex-start;padding:8px 0;animation:rise .35s ease both}
.step i{font-style:normal;min-width:26px;height:26px;border-radius:50%;background:var(--ink);color:#fff;display:grid;place-items:center;font:600 12px 'DM Sans',system-ui,sans-serif}
.q{font-style:italic;color:#3A2A40;padding:8px 10px;border-radius:10px;background:var(--cream);margin-top:6px;font-size:13px}
.q small{font-style:normal;margin-left:6px;font-weight:600}.ok{color:#5B2A86}.no{color:#C0446A}
.warn{margin-top:12px;padding:10px 14px;border-radius:12px;background:#FFF1EA;color:#8A3E1E;font-size:13px}
.ring{position:relative;width:132px;height:132px}.ring b{position:absolute;inset:0;display:grid;place-items:center;font:400 34px Fraunces,Georgia,serif}
.ck{display:grid;grid-template-columns:26px 1fr auto;gap:10px;align-items:start;padding:10px 0;border-top:1px solid #F3EDE6;animation:rise .35s ease both}
.ck .ic{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;color:#fff;font-size:12px;font-weight:700}
.ck .n{font-weight:600;font-size:13.5px}.ck .d{font-size:12.5px;color:#6E5C76;margin-top:2px}
.tag{font:600 10px 'DM Sans',system-ui,sans-serif;letter-spacing:.08em;text-transform:uppercase;border-radius:999px;padding:3px 8px;background:#F3EDF7;color:#5B2A86;white-space:nowrap}
.tag.r{background:#F4F0EA;color:#6E5C76}
.miss{display:inline-block;margin:4px 6px 0 0;padding:5px 10px;border-radius:999px;background:#FFF1EA;color:#B4532F;font-size:12px}
.meta{font-size:11.5px;color:var(--muted);margin-top:10px}
"""

JS = r"""
export default function(component){
 const {data,parentElement}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const D=data,esc=s=>String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;");
 const meta=D.ai?`Read by the AI reader in ${D.ai.seconds}s and double-checked by rules`:`Read by text recognition and rule checks${D.ai_error?" (the AI reader was busy; try again in a moment)":""}`;
 if(D.mode==="letter"){
  const dec=(D.decision||"unclear").toLowerCase(),C={approved:["APPROVED","#5B2A86"],"partially approved":["PARTLY APPROVED","#B4532F"],denied:["DENIED","#C0446A"]}[dec]||[dec.toUpperCase(),"#6E5C76"];
  const chips=[[D.approved_amount,"approved"],[D.requested_amount,"asked for"],[D.start&&D.end?`${D.start} → ${D.end}`:null,"dates"],[D.deadline,"appeal deadline",1]].filter(c=>c[0]);
  root.innerHTML=`<div class="card hero"><div class="stamp" style="color:${C[1]};border-color:${C[1]}">${C[0]}</div>
   <div><div class="sum">${esc(D.summary||"Here is what the letter says.")}</div>
   ${D.reason?`<div style="margin-top:8px;color:#6E5C76;font-size:13.5px"><b>Reason given:</b> ${esc(D.reason)}</div>`:""}
   <div class="chips">${chips.map((c,i)=>`<div class="chip ${c[2]?"hot":""}" style="animation-delay:${i*80}ms"><b>${esc(c[0])}</b><span>${c[1]}</span></div>`).join("")}</div></div></div>
   ${D.conflict?`<div class="warn">${esc(D.conflict)}</div>`:""}
   <div class="cols"><div class="card box"><h4>What to do next</h4>${(D.next_steps||[]).map((s,i)=>`<div class="step" style="animation-delay:${200+i*120}ms"><i>${i+1}</i><div>${esc(s)}</div></div>`).join("")}</div>
   <div class="card box"><h4>${D.questions&&D.questions.length?"Questions to ask":"Where it says so"}</h4>
   ${(D.questions||[]).map(q=>`<div class="step"><i>?</i><div>${esc(q)}</div></div>`).join("")}
   ${(D.quotes||[]).map(q=>`<div class="q">"${esc(q.text)}"<small class="${q.found?"ok":"no"}">${q.found?"✓ on the page":"✕ not found on the page"}</small></div>`).join("")}
   ${!(D.questions||[]).length&&!(D.quotes||[]).length?`<div class="d" style="color:#6E5C76;font-size:13px">Turn on the AI reader for plain-English questions and quotes.</div>`:""}</div></div>
   <div class="meta">${meta}</div>`;
 } else {
  const S=D.score||0,R=56,Cc=2*Math.PI*R,col=S>=85?"#5B2A86":S>=60?"#E0855F":"#C0446A";
  const order={fix:0,unclear:1,pass:2};var ic={pass:["✓","#5B2A86"],fix:["!","#C0446A"],unclear:["?","#E0855F"]};
  const ck=[...(D.checks||[])].map(c=>({...c,status:ic[c.status]?c.status:"unclear"})).sort((a,b)=>order[a.status]-order[b.status]);
  root.innerHTML=`<div class="card hero"><div class="ring"><svg width="132" height="132"><circle cx="66" cy="66" r="${R}" fill="none" stroke="#F3EDE6" stroke-width="12"/>
   <circle id="arc" cx="66" cy="66" r="${R}" fill="none" stroke="${col}" stroke-width="12" stroke-linecap="round" transform="rotate(-90 66 66)"
    stroke-dasharray="${Cc}" stroke-dashoffset="${Cc}" style="transition:stroke-dashoffset 1.1s cubic-bezier(.2,.8,.2,1)"/></svg><b id="sc">0</b></div>
   <div><div class="sum">${esc(D.summary||(D.to_fix?`${D.to_fix} thing${D.to_fix>1?"s":""} to fix before this goes to the payor.`:"Nothing blocking found. A person should still look it over."))}</div>
   <div class="chips"><div class="chip ${D.to_fix?"hot":""}"><b>${D.to_fix}</b><span>to fix</span></div>
   <div class="chip"><b>${ck.filter(c=>c.status==="unclear").length}</b><span>to check</span></div><div class="chip"><b>${ck.filter(c=>c.status==="pass").length}</b><span>ready</span></div></div></div></div>
   <div class="card box" style="margin-top:14px">${ck.map((c,i)=>`<div class="ck" style="animation-delay:${i*60}ms"><div class="ic" style="background:${ic[c.status][1]}">${ic[c.status][0]}</div>
    <div><div class="n">${esc(c.name)}</div><div class="d">${esc(c.detail)}</div>${c.quote?`<div class="q">"${esc(c.quote)}"<small class="${c.found?"ok":"no"}">${c.found?"✓ on the page":"✕ not found"}</small></div>`:""}</div>
    <span class="tag ${c.layer==="rules"?"r":""}">${c.layer==="rules"?"rule check":"AI"}</span></div>`).join("")}
   ${(D.missing||[]).length?`<div style="margin-top:12px"><b style="font-size:13px">Payors usually also ask for</b><br>${D.missing.map(m=>`<span class="miss">${esc(m)}</span>`).join("")}</div>`:""}</div>
   <div class="meta">${meta}</div>`;
  requestAnimationFrame(()=>{root.querySelector("#arc").style.strokeDashoffset=Cc*(1-S/100);
   const el=root.querySelector("#sc"),t0=performance.now();const tick=t=>{const k=Math.min(1,(t-t0)/1000);el.textContent=Math.round(S*(1-Math.pow(1-k,3)));if(k<1)requestAnimationFrame(tick)};requestAnimationFrame(tick)});
 }
}
"""

_component = st.components.v2.component("authops_assist_view", css=CSS, js=JS)


def assist_view(mode: str, result: dict, key: str) -> None:
    keep = {k: v for k, v in result.items() if k not in ("facts",)}
    _component(data={"mode": mode, **keep}, key=key)
