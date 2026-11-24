"""Review deck: one card per extracted field. Swipe right (or press a) if it matches the page,
left (or press r) if it does not. When the deck is done, the verdicts go back to Python."""
from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

from app.widgets.theme import BASE_CSS

CSS = BASE_CSS + """
.qa{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:22px;align-items:start}
@media(max-width:860px){.qa{grid-template-columns:1fr}}
.doc{position:relative;border-radius:16px;overflow:hidden;border:1px solid var(--sand);box-shadow:0 18px 40px -28px rgba(30,5,37,.45);cursor:zoom-in}
.doc img{display:block;width:100%}
.lens{position:absolute;width:190px;height:110px;border-radius:12px;border:2px solid #fff;box-shadow:0 10px 30px rgba(30,5,37,.35);
 background-repeat:no-repeat;pointer-events:none;display:none}
.stack{position:relative;height:300px;margin-top:6px;perspective:1200px}
.cardq{position:absolute;inset:0;background:#fff;border:1px solid var(--sand);border-radius:22px;padding:20px 22px;
 box-shadow:0 22px 44px -30px rgba(30,5,37,.55);touch-action:none;user-select:none;cursor:grab;transition:transform .32s cubic-bezier(.2,.8,.2,1),opacity .32s}
.cardq.drag{transition:none;cursor:grabbing}
.cardq.back{transform:translateY(14px) scale(.95);opacity:.65;pointer-events:none}
.cardq.back2{transform:translateY(26px) scale(.9);opacity:.35;pointer-events:none}
.cardq.back>*,.cardq.back2>*{visibility:hidden}
.tiles{display:flex;flex-wrap:wrap;gap:3px;margin:14px 0 6px}
.tile{min-width:22px;height:34px;padding:0 4px;display:grid;place-items:center;border-radius:6px;background:var(--cream);border:1px solid var(--sand);
 font:600 17px ui-monospace,SFMono-Regular,Menlo,monospace;animation:land .25s ease both}
.tile.sp{background:transparent;border-color:transparent;min-width:10px}
.blank{font:400 22px Fraunces,Georgia,serif;color:var(--muted);margin:16px 0 8px}
.stamp{position:absolute;top:22px;font:800 20px 'DM Sans',system-ui,sans-serif;letter-spacing:.14em;padding:4px 12px;border:3px solid;border-radius:10px;opacity:0}
.st-yes{right:22px;color:#5B2A86;border-color:#5B2A86;transform:rotate(8deg)}.st-no{left:22px;color:#C0446A;border-color:#C0446A;transform:rotate(-8deg)}
.ringw{position:absolute;right:20px;bottom:18px;text-align:center}
.acts{display:flex;justify-content:center;gap:14px;margin-top:18px}
.round{width:58px;height:58px;border-radius:50%;border:1px solid var(--sand);background:#fff;font-size:22px;cursor:pointer;
 transition:transform .15s,box-shadow .15s}.round:hover{transform:scale(1.08);box-shadow:0 10px 22px -14px rgba(30,5,37,.6)}
.round.no{color:#C0446A}.round.yes{color:#5B2A86}
.prog{display:flex;gap:5px;justify-content:center;margin-top:14px}.prog i{width:8px;height:8px;border-radius:50%;background:var(--sand);transition:all .2s}
.prog i.yes{background:#5B2A86}.prog i.no{background:#C0446A}.prog i.cur{transform:scale(1.4);background:var(--peach)}
.done{text-align:center;padding:30px 10px;animation:rise .35s ease both}
.sum{display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin:14px 0}
.chip{font:600 12px 'DM Sans',system-ui,sans-serif;border:1px solid var(--sand);border-radius:999px;padding:5px 11px;cursor:pointer;background:#fff}
.chip.yes{color:#5B2A86}.chip.no{color:#C0446A}
textarea{width:100%;border:1px solid var(--sand);border-radius:12px;padding:10px;font:13px 'DM Sans',system-ui,sans-serif;resize:vertical;min-height:54px;margin:6px 0 12px}
"""

JS = r"""
export default function(component){
 const {data,parentElement,setTriggerValue}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const D=data,F=D.fields;let i=0;const v={};
 root.innerHTML=`<div class="qa"><div><div class="doc" id="doc"><img id="img" src="${D.img}"/><div class="lens" id="lens"></div></div>
   <div class="eyebrow" style="margin-top:8px">${D.caption} · hover to magnify</div></div>
   <div><div class="eyebrow">Does the AI's value match the page?</div><div id="deck"></div></div></div>`;
 const doc=root.querySelector("#doc"),lens=root.querySelector("#lens"),deck=root.querySelector("#deck");
 doc.onmousemove=e=>{const r=doc.getBoundingClientRect(),x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height,Z=2.6;
  lens.style.display="block";lens.style.left=Math.min(r.width-195,Math.max(0,e.clientX-r.left-95))+"px";lens.style.top=Math.max(0,e.clientY-r.top-130)+"px";
  lens.style.backgroundImage=`url(${D.img})`;lens.style.backgroundSize=`${r.width*Z}px auto`;
  lens.style.backgroundPosition=`${-(x*r.width*Z-95)}px ${-(y*r.height*Z-55)}px`};doc.onmouseleave=()=>lens.style.display="none";
 const word=f=>f.value===null?["absent","missing"]:["correct","wrong"];
 function ring(c){const r=17,L=2*Math.PI*r;return `<svg viewBox="0 0 44 44" width="46" height="46"><circle cx="22" cy="22" r="${r}" fill="none" stroke="#ECE5D8" stroke-width="5"/>
  <circle cx="22" cy="22" r="${r}" fill="none" stroke="${c>=.8?"#5B2A86":c>=.55?"#E0855F":"#C0446A"}" stroke-width="5" stroke-linecap="round" stroke-dasharray="${L}" stroke-dashoffset="${L*(1-c)}" transform="rotate(-90 22 22)"/></svg>
  <div class="eyebrow" style="letter-spacing:.05em">${Math.round(c*100)}% sure</div>`}
 function cardHTML(f,cls){const val=f.value===null?`<div class="blank">left blank</div>`:
   `<div class="tiles">${[...String(f.value)].map((ch,k)=>ch===" "?`<span class="tile sp"></span>`:`<span class="tile" style="animation-delay:${k*22}ms">${ch.replace(/</g,"&lt;")}</span>`).join("")}</div>`;
  const [y,n]=word(f);return `<div class="cardq ${cls}"><div class="stamp st-yes">${y.toUpperCase()}</div><div class="stamp st-no">${n.toUpperCase()}</div>
   <div class="eyebrow">${f.label}</div>${val}<div style="font-size:12.5px;color:#6E5C76;max-width:74%">${f.value===null?
   `Swipe right if the page has no ${f.label}; left if it does and the AI missed it.`:`Swipe right if this matches the page exactly; left if anything differs.`}</div>
   <div class="ringw">${ring(f.conf)}</div></div>`}
 function prog(){return `<div class="prog">${F.map((f,k)=>`<i class="${k===i?"cur":v[f.field]?(v[f.field]===word(f)[0]?"yes":"no"):""}"></i>`).join("")}</div>`}
 function render(){if(i>=F.length)return finish();
  deck.innerHTML=`<div class="stack">${F.slice(i+1,i+3).reverse().map((f,k,a)=>cardHTML(f,a.length===2&&k===0?"back2":"back")).join("")}${cardHTML(F[i],"top")}</div>
   <div class="acts"><button class="round no" id="no" title="r">✕</button><button class="round yes" id="yes" title="a">✓</button></div>${prog()}
   <div style="text-align:center;margin-top:8px;font-size:11.5px;color:#8E8292"><span class="kbd">a</span> matches · <span class="kbd">r</span> doesn't · <span class="kbd">←</span> back</div>`;
  const c=deck.querySelector(".cardq.top"),sy=c.querySelector(".st-yes"),sn=c.querySelector(".st-no");let x0=null,dx=0;
  c.onpointerdown=e=>{x0=e.clientX;c.classList.add("drag");c.setPointerCapture(e.pointerId)};
  c.onpointermove=e=>{if(x0===null)return;dx=e.clientX-x0;c.style.transform=`translateX(${dx}px) rotate(${dx/18}deg)`;
   sy.style.opacity=Math.max(0,Math.min(1,dx/120));sn.style.opacity=Math.max(0,Math.min(1,-dx/120))};
  c.onpointerup=()=>{c.classList.remove("drag");if(Math.abs(dx)>110)decide(dx>0);else{c.style.transform="";sy.style.opacity=0;sn.style.opacity=0}x0=null;dx=0};
  deck.querySelector("#yes").onclick=()=>decide(true);deck.querySelector("#no").onclick=()=>decide(false)}
 function decide(yes){const f=F[i],c=deck.querySelector(".cardq.top");v[f.field]=word(f)[yes?0:1];
  c.querySelector(yes?".st-yes":".st-no").style.opacity=1;c.style.transform=`translateX(${yes?520:-520}px) rotate(${yes?24:-24}deg)`;c.style.opacity=0;
  setTimeout(()=>{i++;render()},260)}
 function finish(){const ok=F.filter(f=>v[f.field]===word(f)[0]).length;
  deck.innerHTML=`<div class="done"><div class="serif" style="font-size:30px">Deck done</div>
   <div style="color:#6E5C76;margin-top:4px">${ok} match the page · ${F.length-ok} flagged</div>
   <div class="sum">${F.map((f,k)=>`<span class="chip ${v[f.field]===word(f)[0]?"yes":"no"}" data-k="${k}">${f.label}: ${v[f.field]}</span>`).join("")}</div>
   <textarea id="cm" placeholder="Comment for the team (optional)"></textarea>
   <button class="btn" id="send">${D.can_save?"Submit review":"See how you did"}</button>
   <div style="font-size:11.5px;color:#8E8292;margin-top:8px">Tap a chip to redo that field.</div></div>`;
  deck.querySelectorAll(".chip").forEach(ch=>ch.onclick=()=>{i=+ch.dataset.k;delete v[F[i].field];render()});
  deck.querySelector("#send").onclick=()=>setTriggerValue("submit",{verdicts:v,comment:deck.querySelector("#cm").value.slice(0,500)})}
 const onKey=e=>{if(!root.isConnected){document.removeEventListener("keydown",onKey);return}
  if(e.target.closest&&e.target.closest("input,textarea"))return;if(i>=F.length)return;
  if(e.key==="a")decide(true);else if(e.key==="r")decide(false);else if(e.key==="ArrowLeft"&&i>0){i--;delete v[F[i].field];render()}};
 document.addEventListener("keydown",onKey);render();
 return ()=>document.removeEventListener("keydown",onKey);
}
"""

_component = st.components.v2.component("authops_review_deck", css=CSS, js=JS)


def review_deck(image_path: str | Path, fields: list[dict], caption: str, can_save: bool, key: str):
    """fields: {field, label, value (str or None), conf}. Returns {'verdicts': {...}, 'comment': str} once submitted."""
    img = "data:image/jpeg;base64," + base64.b64encode(Path(image_path).read_bytes()).decode()
    res = _component(data={"img": img, "fields": fields, "caption": caption, "can_save": can_save},
                     key=key, on_submit_change=lambda: None)
    return getattr(res, "submit", None)
