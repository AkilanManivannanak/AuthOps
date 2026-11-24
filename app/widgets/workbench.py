"""Document workbench: watch the page get read, then click any field to spotlight it on the page."""
from __future__ import annotations

import base64
import io

import streamlit as st
from PIL import Image

from app.widgets.theme import BASE_CSS

CSS = BASE_CSS + """
.wb{display:grid;grid-template-columns:minmax(0,6fr) minmax(0,5fr);gap:20px}
@media(max-width:860px){.wb{grid-template-columns:1fr}}
.bar{display:flex;align-items:center;gap:12px;margin-bottom:10px;min-height:38px}
.cap{font-size:13px;color:var(--soft)}
.page{position:relative;overflow:hidden;border-radius:16px;border:1px solid var(--sand);background:#fff;
 box-shadow:0 18px 40px -28px rgba(30,5,37,.45)}
.page img{display:block;width:100%}
.sweep{position:absolute;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,#8C5FB9,transparent);
 box-shadow:0 0 18px 4px rgba(140,95,185,.35);pointer-events:none}
.w{position:absolute;border-radius:2px;background:rgba(140,95,185,.13);animation:land .26s ease-out both;pointer-events:none}
.f{position:absolute;border-radius:3px;border:2px solid;cursor:pointer;animation:land .3s ease-out both;transition:box-shadow .2s}
.f:hover,.f.on{box-shadow:0 0 0 4px rgba(255,180,157,.75)}
.spot{position:absolute;border-radius:4px;pointer-events:none;box-shadow:0 0 0 9999px rgba(30,5,37,.38);transition:all .35s cubic-bezier(.2,.8,.2,1)}
.list{display:flex;flex-direction:column;gap:8px}
.it{padding:12px 14px;cursor:pointer;transition:border-color .15s,box-shadow .15s,transform .15s;animation:rise .3s ease both}
.it:hover{box-shadow:0 10px 24px -20px rgba(30,5,37,.6);transform:translateY(-1px)}
.it.on{border-color:var(--lilac);box-shadow:0 0 0 3px rgba(140,95,185,.14)}
.row{display:flex;justify-content:space-between;align-items:center;gap:10px}
.val{font:400 19px Fraunces,Georgia,serif;margin-top:2px;word-break:break-word}
.conf{height:4px;background:var(--cream);border-radius:4px;margin-top:8px;overflow:hidden}.conf i{display:block;height:100%;border-radius:4px}
.loupe{margin-top:10px;height:74px;border-radius:10px;border:1px solid var(--sand);background-repeat:no-repeat;background-color:#fff}
.why{font-size:12.5px;color:var(--soft);margin-top:8px}
.s-sure{color:#5B2A86;background:#EFE7FA}.s-unsure{color:#B4532F;background:#FFF1EA}.s-abstained{color:#A8355F;background:#FBEAF1}
.keys{font-size:11.5px;color:var(--muted);margin-top:8px}
"""

JS = r"""
export default function(component){
 const {data,parentElement}=component;
 const host=parentElement;let root=host.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";host.appendChild(root);
 const D=data;const COL={sure:"#5B2A86",unsure:"#E0855F",abstained:"#C0446A"};
 const FILL={sure:"rgba(91,42,134,.10)",unsure:"rgba(255,180,157,.28)",abstained:"rgba(192,68,106,.12)"};
 root.innerHTML=`<div class="wb"><div><div class="bar"><button class="btn" id="play">Watch it read</button><span class="cap" id="cap"></span></div>
  <div class="page" id="page"><img id="img" src="${D.img}" alt="document page"/></div>
  <div class="keys"><span class="kbd">j</span> <span class="kbd">k</span> next field · <span class="kbd">r</span> replay</div></div>
  <div><div class="eyebrow" style="margin-bottom:8px">${D.fields.length} fields · ${D.summary}</div><div class="list" id="list"></div></div></div>`;
 const page=root.querySelector("#page"),list=root.querySelector("#list"),cap=root.querySelector("#cap");
 const pct=b=>`left:${b[0]*100}%;top:${b[1]*100}%;width:${b[2]*100}%;height:${b[3]*100}%`;
 let open=D.fields.findIndex(f=>f.status!=="sure");if(open<0)open=0;let timers=[];
 function cards(){list.innerHTML=D.fields.map((f,i)=>`<div class="card it ${i===open?"on":""}" data-i="${i}" style="animation-delay:${i*40}ms">
   <div class="row"><div><div class="eyebrow">${f.label}</div><div class="val">${f.value??'<span style="color:#8E8292">left blank</span>'}</div></div>
   <span class="pill s-${f.status}">${f.status}</span></div>
   <div class="conf"><i style="width:${Math.round(f.conf*100)}%;background:${COL[f.status]}"></i></div>
   ${i===open?(f.boxes.length?`<div class="loupe" id="loupe"></div>`:"")+`<div class="why">${f.why}</div>`:""}</div>`).join("");
  list.querySelectorAll(".it").forEach(el=>el.onclick=()=>{open=+el.dataset.i;cards();spot()});loupe()}
 function loupe(){const el=root.querySelector("#loupe");if(!el)return;const f=D.fields[open];const b=union(f.boxes);
  const W=el.clientWidth||300,H=74,pad=.02;const bw=b[2]+2*pad,bh=b[3]+2*pad;const s=Math.min(W/bw,H/bh)/(1);
  el.style.backgroundImage=`url(${D.img})`;el.style.backgroundSize=`${s}px auto`;
  el.style.backgroundPosition=`${-(b[0]-pad)*s+(W-bw*s)/2}px ${-(b[1]-pad)*s*D.ratio+(H-bh*s*D.ratio)/2}px`;}
 function union(bs){const x0=Math.min(...bs.map(b=>b[0])),y0=Math.min(...bs.map(b=>b[1])),x1=Math.max(...bs.map(b=>b[0]+b[2])),y1=Math.max(...bs.map(b=>b[1]+b[3]));return[x0,y0,x1-x0,y1-y0]}
 function decided(){page.querySelectorAll(".w,.sweep").forEach(e=>e.remove());page.querySelectorAll(".f").forEach(e=>e.remove());
  D.fields.forEach((f,i)=>f.boxes.forEach(b=>{const d=document.createElement("div");d.className="f";d.dataset.i=i;
   d.style.cssText=pct(b)+`;border-color:${COL[f.status]};background:${FILL[f.status]}`;d.title=`${f.label}: ${f.value??"blank"}`;
   d.onclick=()=>{open=i;cards();spot()};page.appendChild(d)}));spot();cap.textContent=D.summary}
 function spot(){let s=page.querySelector(".spot");const f=D.fields[open];
  page.querySelectorAll(".f").forEach(e=>e.classList.toggle("on",+e.dataset.i===open));
  if(!f||!f.boxes.length){if(s)s.remove();return}const b=union(f.boxes),p=.006;
  if(!s){s=document.createElement("div");s.className="spot";page.appendChild(s)}s.style.cssText=pct([b[0]-p,b[1]-p,b[2]+2*p,b[3]+2*p])}
 function play(){timers.forEach(clearTimeout);timers=[];page.querySelectorAll(".w,.f,.spot,.sweep").forEach(e=>e.remove());
  if(matchMedia("(prefers-reduced-motion: reduce)").matches){decided();return}
  const sw=document.createElement("div");sw.className="sweep";page.appendChild(sw);const T=2200,t0=performance.now();
  const words=D.words.slice().sort((a,b)=>a[1]-b[1]);let wi=0;
  const tick=t=>{const f=Math.min(1,(t-t0)/T);sw.style.top=(f*100)+"%";
   while(wi<words.length&&words[wi][1]<=f){const w=words[wi++],d=document.createElement("div");d.className="w";d.style.cssText=pct(w);page.appendChild(d)}
   cap.textContent=f<1?`Reading line by line · ${wi} words`:"";
   if(f<1)timers.push(requestAnimationFrame(tick));else{sw.remove();
    D.fields.forEach((fl,i)=>timers.push(setTimeout(()=>{cap.textContent=`Found ${fl.label}`;fl.boxes.forEach(b=>{const d=document.createElement("div");
     d.className="f";d.dataset.i=i;d.style.cssText=pct(b)+`;border-color:${COL[fl.status]};background:${FILL[fl.status]}`;page.appendChild(d)})},i*120)));
    timers.push(setTimeout(()=>{page.querySelectorAll(".w").forEach(e=>e.style.opacity=".35");decided()},D.fields.length*120+500))}};
  timers.push(requestAnimationFrame(tick))}
 root.querySelector("#play").onclick=play;
 const onKey=e=>{if(!root.isConnected){document.removeEventListener("keydown",onKey);return}
  if(e.target.closest&&e.target.closest("input,textarea,[contenteditable]"))return;
  if(e.key==="j"){open=Math.min(D.fields.length-1,open+1);cards();spot()}if(e.key==="k"){open=Math.max(0,open-1);cards();spot()}if(e.key==="r")play()};
 document.addEventListener("keydown",onKey);
 cards();root.querySelector("#img").complete?play():root.querySelector("#img").onload=play;
 return ()=>{document.removeEventListener("keydown",onKey);timers.forEach(clearTimeout)};
}
"""

_component = st.components.v2.component("authops_workbench", css=CSS, js=JS)


def _img_url(path: str, max_w: int = 1000) -> tuple[str, float, tuple[int, int]]:
    im = Image.open(path).convert("RGB")
    W, H = im.size
    if W > max_w:
        im = im.resize((max_w, int(H * max_w / W)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), H / W, (W, H)


def workbench(page_path: str, words: list, fields: list[dict], summary: str, key: str) -> None:
    """words: [(x, y, w, h)] in source pixels; fields: {label, value, conf, status, why, boxes:[(x,y,w,h)]}."""
    url, ratio, (W, H) = _img_url(page_path)
    norm = lambda b: [round(b[0] / W, 4), round(b[1] / H, 4), round(b[2] / W, 4), round(b[3] / H, 4)]  # noqa: E731
    data = {"img": url, "ratio": ratio, "summary": summary, "words": [norm(w) for w in words],
            "fields": [dict(f, boxes=[norm(b) for b in f["boxes"]]) for f in fields]}
    _component(data=data, key=key)
