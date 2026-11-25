"""Home hero: four big numbers that replay 26 weeks and flip between "with AuthOps" and "without"."""
from __future__ import annotations

import streamlit as st

from app.widgets.theme import BASE_CSS
from authops.monitor.panel import SPECIALTY

CSS = BASE_CSS + """
.bar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:16px}
.seg{display:inline-flex;background:#F4EFF6;border-radius:999px;padding:4px}
.seg button{border:0;background:transparent;font:600 14px 'DM Sans',system-ui,sans-serif;padding:9px 18px;border-radius:999px;cursor:pointer;color:#6E5C76;transition:all .2s}
.seg button.on{background:#1E0525;color:#fff;box-shadow:0 6px 16px -8px rgba(30,5,37,.6)}
.seg button.off.on{background:#C0446A}
.wk{margin-left:auto;display:flex;align-items:center;gap:10px;min-width:300px;flex:1;max-width:460px}
.wk input{flex:1;accent-color:#8C5FB9}.wk b{font:400 18px Fraunces,Georgia,serif;min-width:80px;text-align:right}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}@media(max-width:900px){.tiles{grid-template-columns:repeat(2,1fr)}}
.t{border:1px solid var(--sand);border-radius:20px;padding:20px 22px;background:#fff;transition:background .4s,border-color .4s,transform .2s}
.t:hover{transform:translateY(-2px)}
.t .v{font:300 clamp(40px,4.6vw,62px)/1 Fraunces,Georgia,serif;letter-spacing:-.03em;font-variant-numeric:tabular-nums;transition:color .4s}
.t .l{margin-top:10px;font-size:13.5px;color:#4A3A50}.t .d{margin-top:6px;font:600 12px 'DM Sans',system-ui,sans-serif;height:16px}
.t.bad{background:#FDF1F5;border-color:#F4C9D8}.t.bad .v{color:#A8355F}
.t.good{background:linear-gradient(135deg,#FDF8F3,#F7F0FB)}.t.good .v{color:#5B2A86}
.chart{margin-top:14px;border:1px solid var(--sand);border-radius:20px;background:#fff;padding:14px 16px 6px}
.lg{display:flex;gap:16px;font-size:12px;color:#6E5C76}.lg i{display:inline-block;width:18px;height:3px;border-radius:2px;margin-right:6px;vertical-align:middle}
svg text{font-family:'DM Sans',system-ui,sans-serif}
"""

JS = r"""
export default function(component){
 const {data,parentElement}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const D=data,W=D.weeks;let wk=1,mode="with",raf=null,shown=[0,0,0,0];
 root.innerHTML=`<div class="bar"><div class="seg"><button data-m="with" class="on">With AuthOps</button><button data-m="without" class="off">Without</button></div>
  <button class="btn ghost" id="pl">Replay</button><div class="wk"><input type="range" id="sl" min="1" max="${W}" value="1"><b id="wl">Week 1</b></div></div>
  <div class="tiles">${[0,1,2,3].map(i=>`<div class="t" id="t${i}"><div class="v" id="v${i}">0</div><div class="l">${D.labels[i]}</div><div class="d" id="d${i}"></div></div>`).join("")}</div>
  <div class="chart"><div class="lg"><span><i style="background:#C0446A"></i>dollars denied without AuthOps</span><span><i style="background:#5B2A86"></i>with AuthOps</span></div>
  <svg id="sv" viewBox="0 0 900 190" width="100%"></svg></div>`;
 const fmt=(i,v)=>i===1?"$"+Math.round(v).toLocaleString():i===2?Math.round(v)+"%":Math.round(v).toLocaleString();
 const val=(m,i,w)=>D[m][i][w-1];
 function tiles(animate){const tgt=[0,1,2,3].map(i=>val(mode,i,wk));const from=[...shown],t0=performance.now();cancelAnimationFrame(raf);
  const step=t=>{const k=animate?Math.min(1,(t-t0)/600):1,e=1-Math.pow(1-k,3);
   tgt.forEach((v,i)=>{shown[i]=from[i]+(v-from[i])*e;root.querySelector("#v"+i).textContent=fmt(i,shown[i])});if(k<1)raf=requestAnimationFrame(step)};raf=requestAnimationFrame(step);
  [0,1,2,3].forEach(i=>{const w=val("with",i,wk),o=val("without",i,wk),better=D.better[i]>0?w>o:w<o,t=root.querySelector("#t"+i);
   t.className="t "+(mode==="without"&&w!==o?"bad":mode==="with"&&w!==o?"good":"");
   root.querySelector("#d"+i).innerHTML=w===o?"":mode==="with"?`<span style="color:#5B2A86">${w<o?"▼":"▲"} from ${fmt(i,o)} without AuthOps</span>`:`<span style="color:#A8355F">vs ${fmt(i,w)} with AuthOps</span>`})}
 function chart(){const a=D.cum_without,b=D.cum_with,mx=Math.max(1,...a),X=i=>40+i/(W-1)*840,Y=v=>170-v/mx*150;
  const pa=a.slice(0,wk).map((v,i)=>`${i?"L":"M"}${X(i)},${Y(v)}`).join(""),pb=b.slice(0,wk).map((v,i)=>`${i?"L":"M"}${X(i)},${Y(v)}`).join("");
  const gap=wk>1?`M${X(0)},${Y(a[0])}`+a.slice(1,wk).map((v,i)=>`L${X(i+1)},${Y(v)}`).join("")+b.slice(0,wk).map((v,i)=>[i,v]).reverse().map(([i,v])=>`L${X(i)},${Y(v)}`).join("")+"Z":"";
  const kept=a[wk-1]-b[wk-1];
  root.querySelector("#sv").innerHTML=`<line x1="40" x2="880" y1="170" y2="170" stroke="#F0EAE2"/><path d="${gap}" fill="#FFB49D" opacity=".28"/>
   <path d="${pa}" fill="none" stroke="#C0446A" stroke-width="3"/><path d="${pb}" fill="none" stroke="#5B2A86" stroke-width="3"/>
   ${wk>2?`<text x="${X(wk-1)-6}" y="${(Y(a[wk-1])+Y(b[wk-1]))/2+5}" text-anchor="end" font-size="15" fill="#B4532F" font-weight="600">$${Math.round(kept).toLocaleString()} kept</text>`:""}
   <text x="40" y="186" font-size="11" fill="#8E8292">week 1</text><text x="880" y="186" font-size="11" text-anchor="end" fill="#8E8292">week ${W}</text>`}
 function set(w,animate=true){wk=w;root.querySelector("#sl").value=w;root.querySelector("#wl").textContent="Week "+w;tiles(animate);chart()}
 let pt=null;function play(){clearInterval(pt);let w=1;set(1,false);pt=setInterval(()=>{w++;set(w,false);if(w>=W){clearInterval(pt);tiles(true)}},140)}
 root.querySelector("#sl").oninput=e=>{clearInterval(pt);set(+e.target.value)};
 root.querySelector("#pl").onclick=play;
 root.querySelectorAll(".seg button").forEach(b=>b.onclick=()=>{mode=b.dataset.m;root.querySelectorAll(".seg button").forEach(x=>x.classList.toggle("on",x===b));tiles(true)});
 play();return ()=>{clearInterval(pt);cancelAnimationFrame(raf)};
}
"""

_component = st.components.v2.component("authops_pulse", css=CSS, js=JS)


def _value(e: dict) -> float:
    s = SPECIALTY[e["spec"]]
    return e["units"] / s["units_per_visit"] * s["rate"]


def pulse_data(floor: dict) -> dict:
    """Weekly cumulative numbers for the real 26-week run, and the same requests without AuthOps:
    requests held and fixed before submission would have gone out and been denied, and requests sent at the
    amount the payor approves in full would have asked for the full clinical need and come back partial."""
    E, W = floor["events"], 26
    out = {"with": [[], [], [], []], "without": [[], [], [], []], "cum_with": [], "cum_without": []}
    for w in range(W):
        L = [e for e in E if e["week"] <= w]
        sent = [e for e in L if e["outcome"] != "caught"]
        caught = [e for e in L if e["outcome"] == "caught"]
        denied = [e for e in L if e["outcome"] == "denied"]
        full = [e for e in L if e["outcome"] == "approved"]
        full_wo = [e for e in full if (e.get("recommended") or e["units"]) >= e["units"]]
        d_with = sum(_value(e) for e in denied)
        d_wo = d_with + sum(_value(e) for e in caught)
        for m, vals in (("with", [len(denied), d_with, 100 * len(full) / max(1, len(sent)), len(caught)]),
                        ("without", [len(denied) + len(caught), d_wo, 100 * len(full_wo) / max(1, len(L)), 0])):
            for i, v in enumerate(vals):
                out[m][i].append(round(v, 1))
        out["cum_with"].append(round(d_with))
        out["cum_without"].append(round(d_wo))
    out.update({"weeks": W, "better": [-1, -1, 1, 1],
                "labels": ["requests denied by the payor", "billed value of denied requests",
                           "approved in full the first time", "fixed before the payor saw them"]})
    return out


def pulse(floor: dict, key: str = "pulse") -> None:
    _component(data=pulse_data(floor), key=key)
