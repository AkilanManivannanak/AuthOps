"""Today board: four counts and every patient as a card in the stage it is in. Click a card to open it."""
from __future__ import annotations

import streamlit as st

from app.widgets.theme import BASE_CSS

CSS = BASE_CSS + """
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}@media(max-width:900px){.tiles{grid-template-columns:repeat(2,1fr)}}
.t{border:1px solid var(--sand);border-radius:20px;padding:18px 20px;background:#fff;cursor:pointer;transition:all .2s;text-align:left;font:inherit;color:inherit}
.t:hover{transform:translateY(-2px);box-shadow:0 14px 30px -24px rgba(30,5,37,.6)}
.t.on{border-color:#1E0525;box-shadow:0 0 0 2px #1E0525 inset}
.t .v{font:300 clamp(40px,4.4vw,58px)/1 Fraunces,Georgia,serif;letter-spacing:-.03em;font-variant-numeric:tabular-nums}
.t .l{margin-top:8px;font-size:13.5px;color:#4A3A50}
.t.warn{background:linear-gradient(135deg,#FFF6F1,#FDEBF0)}.t.warn .v{color:#B4532F}
.t.ok .v{color:#5B2A86}
.cols{display:grid;grid-template-columns:repeat(6,minmax(170px,1fr));gap:10px;overflow-x:auto;padding-bottom:6px}
.col{background:#FBF8F5;border:1px solid #F0EAE2;border-radius:18px;padding:10px;min-height:220px;transition:opacity .25s}
.col.dim{opacity:.35}
.ch{display:flex;justify-content:space-between;align-items:center;padding:4px 6px 10px;font:600 12px 'DM Sans',system-ui,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:#6E5C76}
.ch b{font:400 18px Fraunces,Georgia,serif;color:#1E0525;letter-spacing:0}
.card2{background:#fff;border:1px solid #ECE5D8;border-radius:14px;padding:10px 12px;margin-bottom:8px;cursor:pointer;transition:all .18s;animation:rise .35s ease both;position:relative}
.card2:hover{border-color:#8C5FB9;transform:translateY(-1px);box-shadow:0 10px 20px -16px rgba(30,5,37,.6)}
.card2 .n{font-weight:600;font-size:13.5px}.card2 .m{font-size:11.5px;color:#8E8292;margin-top:2px}
.card2 .s{font-size:11.5px;margin-top:6px;display:inline-block;border-radius:8px;padding:3px 8px;line-height:1.35}
.s.warn{background:#FFF1EA;color:#B4532F}.s.ok{background:#EFE7FA;color:#5B2A86}.s.bad{background:#FBEAF1;color:#A8355F}
.s.info{background:#EEF0FA;color:#4B4F8A}.s.neutral{background:#F4F0EA;color:#6E5C76}
.card2.pulse:after{content:"";position:absolute;right:10px;top:12px;width:8px;height:8px;border-radius:50%;background:#C0446A;animation:beat 1.6s infinite}
@keyframes beat{0%{box-shadow:0 0 0 0 rgba(192,68,106,.5)}70%{box-shadow:0 0 0 8px rgba(192,68,106,0)}100%{box-shadow:0 0 0 0 rgba(192,68,106,0)}}
.empty{font-size:12px;color:#B3A7B8;padding:10px 6px}
"""

JS = r"""
export default function(component){
 const {data,parentElement,setTriggerValue}=component;
 let root=parentElement.querySelector(".root");if(root)root.remove();
 root=document.createElement("div");root.className="root";parentElement.appendChild(root);
 const D=data;let focus=null;const esc=s=>String(s??"").replace(/&/g,"&amp;").replace(/</g,"&lt;");
 root.innerHTML=`<div class="tiles">${D.tiles.map((t,i)=>`<button class="t ${t.tone}" data-c="${t.cols.join(",")}"><div class="v" data-v="${t.value}">0</div><div class="l">${t.label}</div></button>`).join("")}</div>
  <div class="cols">${D.cols.map(c=>`<div class="col" data-k="${c.key}"><div class="ch">${c.label}<b>${c.cards.length}</b></div>
   ${c.cards.length?c.cards.map((p,i)=>`<div class="card2 ${p.tone==="warn"||p.tone==="bad"?"pulse":""}" data-id="${p.id}" style="animation-delay:${i*40}ms">
    <div class="n">${esc(p.name)}</div><div class="m">${esc(p.service)} · ${esc(p.payor)}</div><span class="s ${p.tone}">${esc(p.detail||p.label)}</span></div>`).join(""):`<div class="empty">Nothing here</div>`}</div>`).join("")}</div>`;
 root.querySelectorAll(".v").forEach(el=>{const to=+el.dataset.v,t0=performance.now();const tick=t=>{const k=Math.min(1,(t-t0)/800);el.textContent=Math.round(to*(1-Math.pow(1-k,3)));if(k<1)requestAnimationFrame(tick)};requestAnimationFrame(tick)});
 root.querySelectorAll(".t").forEach(b=>b.onclick=()=>{const c=b.dataset.c.split(",");focus=focus===b.dataset.c?null:b.dataset.c;
  root.querySelectorAll(".t").forEach(x=>x.classList.toggle("on",focus&&x===b));
  root.querySelectorAll(".col").forEach(col=>col.classList.toggle("dim",!!focus&&!c.includes(col.dataset.k)))});
 root.querySelectorAll(".card2").forEach(c=>c.onclick=()=>setTriggerValue("open",c.dataset.id));
}
"""

_component = st.components.v2.component("authops_board", css=CSS, js=JS)


def board(tiles: list[dict], cols: list[dict], key: str = "board") -> str | None:
    res = _component(data={"tiles": tiles, "cols": cols}, key=key, on_open_change=lambda: None)
    return getattr(res, "open", None)
