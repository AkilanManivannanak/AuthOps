import json
import random

import streamlit as st
import streamlit.components.v1 as components

from app.ui import FOREST, RED, log, setup
from authops.ops.experiments import QARamp

setup("Autonomy Ramp",
      "A new portal starts with every submission checked by a person. The gate lowers that share only while results "
      "hold, and snaps it back when they slip. Plant a hidden regression and watch the gate catch it.")

c1, c2, c3, c4 = st.columns(4)
base = c1.slider("Agent error rate when healthy", 0.0, 0.10, 0.02, 0.005, format="%.3f")
fault = c2.slider("Error rate after the portal changes", 0.05, 0.6, 0.25, 0.01)
fault_day = c3.slider("Portal changes on day", 10, 50, 30)
fixed = c4.slider("Comparison: fixed QA share", 0.0, 1.0, 0.10, 0.05)
d1, d2, d3 = st.columns([1, 1, 2])
per_day = d1.slider("Submissions per day", 10, 100, 40, 10)
window = d2.slider("Gate window (runs)", 10, 60, 20, 5)
if "ramp_seed" not in st.session_state:
    st.session_state.ramp_seed = 1
if d3.button("Roll again (new random day-to-day noise)"):
    st.session_state.ramp_seed += 1


def simulate(seed):
    rng = random.Random(seed)
    ramp = QARamp(window=window, floor=0.05, step=0.15, min_success=0.9, min_smooth=0, seed=seed, max_silent=1)
    days, share, gated_err, fixed_err, reviews = [], [], [], [], []
    for d in range(60):
        rate = fault if d >= fault_day else base
        g = f = r = 0
        for _ in range(per_day):
            wrong = rng.random() < rate
            routed = ramp.route_to_qa("p")
            r += routed
            if wrong and not routed:
                g += 1
            if wrong and rng.random() >= fixed:
                f += 1
            # QA sees routed runs; auto-submitted runs are audited later, so silent errors reach the gate too
            ramp.record("p", success=not wrong, smooth=100, silent_error=wrong and not routed)
        days.append(d + 1)
        share.append(round(ramp.state["p"].qa_share, 3))
        gated_err.append(g)
        fixed_err.append(f)
        reviews.append(r)
    return {"days": days, "share": share, "gated": gated_err, "fixed": fixed_err, "reviews": reviews}


s = simulate(st.session_state.ramp_seed)
tot_g, tot_f = sum(s["gated"]), sum(s["fixed"])
rev_g, rev_f = sum(s["reviews"]), round(fixed * per_day * 60)
log("ramp_sim", {"base": base, "fault": fault, "day": fault_day, "fixed": fixed, "gated_errors": tot_g, "fixed_errors": tot_f})

html = f"""
<style>body{{margin:0;font-family:Inter,system-ui,sans-serif;color:#1F2A24}} .k{{display:flex;gap:26px;margin:4px 0 10px}}
.k div{{font-family:Fraunces,Georgia,serif;font-weight:300;font-size:2.2rem}} .k span{{display:block;font-family:Inter;font-size:.8rem;color:#6C6C6C}}
button{{border:0;border-radius:999px;padding:7px 18px;font-weight:700;background:#1F2A24;color:#FAF8F4;cursor:pointer}}</style>
<div class="k"><div id="a" style="color:{FOREST}">0<span>wrong submissions reaching payors, with the gate</span></div>
<div id="b" style="color:{RED}">0<span>with a fixed {round(fixed * 100)}% QA share</span></div>
<div id="c">0<span>human reviews used by the gate (fixed: {rev_f:,})</span></div></div>
<div style="font-size:.8rem;color:#6C6C6C">Human QA share</div><svg id="s1" viewBox="0 0 900 140" width="100%"></svg>
<div style="font-size:.8rem;color:#6C6C6C;margin-top:4px">Wrong submissions reaching payors per day:
<b style="color:{FOREST}">with the gate</b> vs <b style="color:#B3402F">fixed QA share</b></div>
<svg id="s2" viewBox="0 0 900 170" width="100%"></svg><button id="pl">Replay</button>
<script>
const S={json.dumps(s)}, W=900,L=40,R=50, n=S.days.length, FD={fault_day - 1};
const maxE=Math.max(1,...S.fixed,...S.gated), NS='http://www.w3.org/2000/svg';
const x=i=>L+i/(n-1)*(W-L-R);
function el(sv,t,a){{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);sv.appendChild(e);return e;}}
function panel(sv,H,series,maxv,fmt,k){{ sv.innerHTML=''; const T=8,B=22, y=v=>T+(1-v/maxv)*(H-T-B);
  el(sv,'rect',{{x:x(FD),y:T,width:W-R-x(FD),height:H-T-B,fill:'#B3402F',opacity:.06}});
  for(let g=0;g<=2;g++){{const v=maxv*g/2; el(sv,'line',{{x1:L,x2:W-R,y1:y(v),y2:y(v),stroke:'#E4E1D8'}});
    el(sv,'text',{{x:W-R+6,y:y(v)+4,'font-size':11,fill:'#6C6C6C'}}).textContent=fmt(v);}}
  series.forEach(([arr,col,dash,w])=>el(sv,'path',{{d:arr.slice(0,k).map((v,i)=>(i?'L':'M')+x(i).toFixed(1)+','+y(v).toFixed(1)).join(''),
    fill:'none',stroke:col,'stroke-width':w,'stroke-dasharray':dash}}));
  el(sv,'text',{{x:x(FD)+5,y:T+12,'font-size':11,fill:'#B3402F'}}).textContent='portal changed';
  el(sv,'text',{{x:L,y:H-6,'font-size':11,fill:'#6C6C6C'}}).textContent='day 1';
  el(sv,'text',{{x:W-R-36,y:H-6,'font-size':11,fill:'#6C6C6C'}}).textContent='day 60';}}
function draw(k){{
  panel(document.getElementById('s1'),140,[[S.share,'#1F2A24','',3]],1,v=>Math.round(v*100)+'%',k);
  panel(document.getElementById('s2'),170,[[S.fixed,'#B3402F','5 4',2],[S.gated,'{FOREST}','',2.5]],maxE,v=>Math.round(v),k);
  const sum=a=>a.slice(0,k).reduce((s,v)=>s+v,0);
  document.getElementById('a').firstChild.nodeValue=sum(S.gated); document.getElementById('b').firstChild.nodeValue=sum(S.fixed);
  document.getElementById('c').firstChild.nodeValue=sum(S.reviews).toLocaleString();}}
function play(){{let k=0;const id=setInterval(()=>{{k++;draw(k);if(k>=n)clearInterval(id);}},70);}}
document.getElementById('pl').onclick=play; play();
</script>"""
components.html(html, height=520)

st.markdown(f"""**Read it:** over 60 days the gate let **{tot_g}** wrong submissions through while using **{rev_g:,}** human
reviews. A fixed {fixed:.0%} QA share let **{tot_f}** through using about **{rev_f:,}** reviews. The trade-off to look for:
the gate spends reviews early and right after the portal changes, and almost none in between.""")
with st.expander("How the gate decides"):
    st.markdown(f"""- Every {window} runs it looks at the window: success rate, and silent errors found by audit.
- If success is at least 90% and at most one silent error turned up in audit, the QA share drops by 15 points (floor 5%).
- If success falls more than 15 points below target or more than one silent error appears, the share jumps up by 30 points.
- The same `QARamp` class runs in the real pipeline (`authops/ops/experiments.py`); this page only feeds it simulated outcomes.""")
