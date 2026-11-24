"""Proof wall: cards with an animated figure on the front; tap to flip to how it was measured."""
from __future__ import annotations

import json

import streamlit as st

HTML = r"""
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400&family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--ink:#1E0525;--violet:#5B2A86;--lilac:#8C5FB9;--rose:#C0446A;--sand:#ECE5D8;--cream:#FDF8F3;--muted:#8E8292}
*{box-sizing:border-box}body{margin:0;font-family:'DM Sans',system-ui,sans-serif;color:var(--ink);background:transparent}
.wall{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
@media(max-width:900px){.wall{grid-template-columns:repeat(2,1fr)}}@media(max-width:600px){.wall{grid-template-columns:1fr}}
.c{height:268px;perspective:1200px;cursor:pointer}
.in{position:relative;width:100%;height:100%;transition:transform .6s cubic-bezier(.2,.8,.2,1);transform-style:preserve-3d}
.c.f .in{transform:rotateY(180deg)}.c:hover .in{box-shadow:0 18px 36px -28px rgba(30,5,37,.55);border-radius:20px}
.fa{position:absolute;inset:0;backface-visibility:hidden;-webkit-backface-visibility:hidden;border-radius:20px;padding:18px 20px;display:flex;flex-direction:column;justify-content:space-between}
.fr{background:#fff;border:1px solid var(--sand)}.bk{background:var(--ink);color:#FDF8F3;transform:rotateY(180deg)}
.t{font-weight:700;font-size:15px}.hint{font-size:11.5px;color:var(--muted)}.bk .hint{color:#C9B8D3}
.bk p{font-size:13px;line-height:1.5;margin:0;color:#E9DDF0}
.pct{font:400 38px Fraunces,Georgia,serif;font-variant-numeric:tabular-nums;line-height:1}
.sub{font-size:12.5px;color:var(--muted)}.pill{display:inline-block;font:700 11px 'DM Sans';padding:3px 9px;border-radius:999px;background:#EFE7FA;color:#5B2A86;margin-top:6px}
.bar{height:12px;background:var(--cream);border-radius:9px;margin-top:4px;overflow:hidden}.bar i{display:block;height:100%;border-radius:9px;width:0;transition:width .9s cubic-bezier(.2,.7,.2,1)}
.row{display:flex;justify-content:space-between;font-size:12.5px;margin-top:8px}
.dots{display:flex;flex-wrap:wrap;gap:4px;max-width:8.5rem}.dots i{width:11px;height:11px;border-radius:50%;transform:scale(0);transition:transform .3s ease}
</style>
<div class="wall" id="w"></div>
<script>
const C=__CARDS__;const w=document.getElementById("w");
const ring=c=>{const s=c.n?c.k/c.n:0,r=46,L=2*Math.PI*r;return `<div style="display:flex;gap:14px;align-items:center">
 <svg viewBox="0 0 112 112" width="100" height="100"><circle cx="56" cy="56" r="${r}" fill="none" stroke="#ECE5D8" stroke-width="11"/>
 <circle class="arc" cx="56" cy="56" r="${r}" fill="none" stroke="#5B2A86" stroke-width="11" stroke-linecap="round" stroke-dasharray="${L}" stroke-dashoffset="${L}" data-to="${L*(1-s)}" transform="rotate(-90 56 56)" style="transition:stroke-dashoffset 1.1s cubic-bezier(.2,.7,.2,1)"/></svg>
 <div><div class="pct">${(s*100).toFixed(s>=.995?2:1)}%</div><div class="sub">${c.k.toLocaleString()} of ${c.n.toLocaleString()}</div>${c.note?`<span class="pill">${c.note}</span>`:""}</div></div>`};
const versus=c=>{const mx=Math.max(c.left,c.right)||1,col=c.good===false?"#C0446A":"#5B2A86";return `<div class="pct" style="font-size:28px;color:${col}">${c.headline}</div>
 <div class="row"><span>${c.left_label}</span><b>${c.left}</b></div><div class="bar"><i data-w="${c.left/mx*100}" style="background:#B3A7B8"></i></div>
 <div class="row"><b>${c.right_label}</b><b>${c.right}</b></div><div class="bar"><i data-w="${c.right/mx*100}" style="background:${col}"></i></div>`};
const dots=c=>{const f=(n,col)=>`<div class="dots">${Array.from({length:n},(_,i)=>`<i style="background:${col};transition-delay:${i*35}ms"></i>`).join("")}</div>`;
 return `<div style="display:grid;grid-template-columns:1fr auto 1fr;gap:10px;align-items:center"><div>${f(c.left,"#C0446A")}<div class="sub" style="margin-top:6px">${c.left_label} <b>${c.left}</b></div></div>
 <div class="pct" style="font-size:22px;color:#8E8292">vs</div><div>${f(c.right,"#5B2A86")}<div class="sub" style="margin-top:6px">${c.right_label} <b>${c.right}</b></div></div></div>`};
w.innerHTML=C.map((c,i)=>`<div class="c" data-i="${i}"><div class="in"><div class="fa fr"><div class="t">${c.title}</div>${c.kind==="ring"?ring(c):c.kind==="versus"?versus(c):dots(c)}<div class="hint">Tap to see how it was measured</div></div>
 <div class="fa bk"><div class="t">${c.title}</div><p>${c.method}</p><div class="hint">Tap to flip back</div></div></div></div>`).join("");
w.querySelectorAll(".c").forEach(e=>e.onclick=()=>e.classList.toggle("f"));
const io=new IntersectionObserver(es=>es.forEach(en=>{if(!en.isIntersecting)return;const el=en.target;
 el.querySelectorAll(".arc").forEach(a=>a.style.strokeDashoffset=a.dataset.to);
 el.querySelectorAll(".bar i").forEach(b=>b.style.width=b.dataset.w+"%");
 el.querySelectorAll(".dots i").forEach(d=>d.style.transform="scale(1)");io.unobserve(el)}),{threshold:.3});
w.querySelectorAll(".c").forEach(c=>io.observe(c));
</script>
"""


def proof_wall(cards: list[dict]) -> None:
    st.iframe(HTML.replace("__CARDS__", json.dumps(cards)), height="content")
