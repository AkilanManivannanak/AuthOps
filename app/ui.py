"""Shared look, components and tester identity for the AuthOps app.

Design language: warm paper background, ink text, forest green for "earned/working",
brick red for "failed/at risk", serif light display figures, numbers that count up,
rings and bars that sweep in once, cards that flip to show how a number was measured.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "app" / "assets"
FOREST, GREEN, RED, INK, RULE, PAPER, TAG, AMBER = (
    "#28543E", "#609D7B", "#B3402F", "#1F2A24", "#E4E1D8", "#FAF8F4", "#F4E27A", "#C98B1E")

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400&family=Inter:wght@400;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, p, li, label, input, textarea, button {{ font-family: 'Inter', system-ui, sans-serif; }}
h1, h2, h3 {{ font-family: 'Fraunces', Georgia, serif !important; font-weight: 300 !important; letter-spacing: -0.01em; color: {INK}; }}
h1 {{ font-size: 3rem !important; line-height: 1.05 !important; }}
.block-container {{ padding-top: 2.2rem; max-width: 1280px; }}
.ao-sub {{ color: #6C6C6C; font-size: 1.02rem; margin-top: -0.6rem; margin-bottom: 1.4rem; max-width: 760px; }}
.ao-tile {{ border: 1px solid {RULE}; background: #fff; border-radius: 18px; padding: 18px 20px; transition: all .18s ease; height: 100%; }}
.ao-tile:hover {{ transform: translateY(-2px); box-shadow: 0 8px 24px rgba(31,42,36,.10); border-color: {FOREST}; }}
.ao-tile.hot {{ background: {TAG}; border-color: {INK}; }}
.ao-fig {{ font-family: 'Fraunces', Georgia, serif; font-weight: 300; font-size: 2.9rem; line-height: 1; font-variant-numeric: tabular-nums; }}
.ao-lab {{ margin-top: 8px; font-size: .9rem; color: #444; }}
.ao-pill {{ display:inline-block; border-radius: 999px; padding: 2px 10px; font-size: .78rem; font-weight: 700; }}
.ao-ok {{ background: {FOREST}; color: {PAPER}; }} .ao-bad {{ background: {RED}; color: #fff; }} .ao-warn {{ background: {AMBER}; color: #fff; }}
.ao-muted {{ color: #6C6C6C; font-size: .88rem; }}
.ao-card {{ border:1px solid {RULE}; background:#fff; border-radius: 16px; padding: 16px 18px; margin-bottom: 10px; }}
.ao-check {{ display:flex; gap:10px; align-items:flex-start; padding:8px 0; border-bottom:1px solid {RULE}; animation: aoIn .35s ease both; }}
@keyframes aoIn {{ from {{ opacity:0; transform: translateY(6px); }} to {{ opacity:1; transform:none; }} }}
div[data-testid="stMetricValue"] {{ font-family: 'Fraunces', Georgia, serif; font-weight: 300; }}
section[data-testid="stSidebar"] {{ background: #F1EEE6; }}
.stButton>button {{ border-radius: 999px; font-weight: 600; }}
.stTabs [data-baseweb="tab"] {{ font-weight: 600; }}
</style>
"""


def setup(title: str, purpose: str = "") -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(f"<h1>{title}</h1>", unsafe_allow_html=True)
    if purpose:
        st.markdown(f"<div class='ao-sub'>{purpose}</div>", unsafe_allow_html=True)
    log("view", {"title": title})


# ------------------------------------------------------------------ data

@st.cache_data(show_spinner=False)
def asset_json(name: str):
    p = ASSETS / name
    return json.loads(p.read_text()) if p.exists() else None


@st.cache_resource(show_spinner=False)
def store():
    from authops.ops.userstore import UserStore

    return UserStore()


def tester() -> dict | None:
    return st.session_state.get("tester")


def session_id() -> str:
    if "sid" not in st.session_state:
        t = tester()
        st.session_state.sid = store().start_session(t["id"] if t else None)
    return st.session_state.sid


def log(action: str, payload: dict | None = None, page: str | None = None) -> None:
    try:
        t = tester()
        store().event(session_id(), t["id"] if t else None, page or st.session_state.get("page", ""), action, payload)
    except Exception:
        pass  # logging must never break the app


def require_tester(reason: str = "so your work counts in the study") -> dict | None:
    t = tester()
    if not t:
        st.info(f"Join as a tester on the **Join the study** page {reason}. You can still explore without joining.")
    return t


# ------------------------------------------------------------------ components

# Lets a components.html iframe grow or shrink to fit its content when the grid wraps on narrow screens.
AUTOSIZE = """<script>(function(){const send=()=>window.parent.postMessage({isStreamlitMessage:true,
type:"streamlit:setFrameHeight",height:Math.ceil(document.documentElement.scrollHeight)},"*");
new ResizeObserver(send).observe(document.body);window.addEventListener("load",send);setTimeout(send,150);})();</script>"""


def tiles(items: list[tuple]) -> None:
    """items: (value, label, fmt, hot) ; values count up in the browser."""
    cells = ""
    for i, (value, label, fmt, hot) in enumerate(items):
        cells += (f"<div class='ao-tile {'hot' if hot else ''}'><div class='ao-fig' data-to='{value}' data-fmt='{fmt}' "
                  f"id='t{i}'>0</div><div class='ao-lab'>{label}</div></div>")
    html = f"""{CSS}<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px">{cells}</div>
    <script>
    const ease=t=>1-Math.pow(1-t,3);
    document.querySelectorAll('.ao-fig').forEach(el=>{{
      const to=parseFloat(el.dataset.to), fmt=el.dataset.fmt, t0=performance.now(), dur=1100;
      const show=v=> fmt==='pct'? (v*100).toFixed(1)+'%' : fmt==='pct0'? Math.round(v*100)+'%' :
                     fmt==='f1'? v.toFixed(1) : Math.round(v).toLocaleString();
      const step=n=>{{const f=Math.min(1,(n-t0)/dur); el.textContent=show(to*ease(f)); if(f<1) requestAnimationFrame(step);}};
      requestAnimationFrame(step);
    }});
    </script>{AUTOSIZE}"""
    components.html(html, height=168)


def proof_cards(cards: list[dict], height: int = 300) -> None:
    """Flip cards. card: {title, kind: ring|versus|dots, ..., method}."""
    blocks = []
    for i, c in enumerate(cards):
        if c["kind"] == "ring":
            share = c["k"] / c["n"] if c["n"] else 0
            r, circ = 52, 2 * 3.14159 * 52
            front = f"""<svg viewBox="0 0 128 128" width="112" height="112"><circle cx="64" cy="64" r="{r}" fill="none" stroke="{RULE}" stroke-width="12"/>
              <circle class="sweep" cx="64" cy="64" r="{r}" fill="none" stroke="{FOREST}" stroke-width="12" stroke-linecap="round"
              stroke-dasharray="{circ}" stroke-dashoffset="{circ}" data-to="{circ * (1 - share)}" transform="rotate(-90 64 64)"/></svg>
              <div><div class="big">{share * 100:.1f}%</div><div class="mut">{c['k']:,} of {c['n']:,}</div>
              {f"<span class='pill'>{c['note']}</span>" if c.get('note') else ''}</div>"""
            front = f"<div style='display:flex;gap:14px;align-items:center'>{front}</div>"
        elif c["kind"] == "versus":
            mx = max(c["left"], c["right"]) or 1
            col = FOREST if c.get("good", True) else RED
            front = f"""<div class="big" style="color:{col}">{c['headline']}</div>
              <div class="bar"><div class="lbl"><span>{c['left_label']}</span><b>{c['left']}</b></div><div class="track"><div class="fill" data-w="{c['left'] / mx * 100}" style="background:#9A9A9A"></div></div></div>
              <div class="bar"><div class="lbl"><span><b>{c['right_label']}</b></span><b>{c['right']}</b></div><div class="track"><div class="fill" data-w="{c['right'] / mx * 100}" style="background:{col}"></div></div></div>"""
        else:
            dots_l = "".join(f"<i style='background:{RED};transition-delay:{j * 40}ms'></i>" for j in range(c["left"]))
            dots_r = "".join(f"<i style='background:{FOREST};transition-delay:{j * 40}ms'></i>" for j in range(c["right"]))
            front = f"""<div style="display:grid;grid-template-columns:1fr auto 1fr;gap:10px;align-items:center">
              <div><div class="dots">{dots_l}</div><div class="mut">{c['left_label']} <b>{c['left']}</b></div></div>
              <div class="big mut">vs</div><div><div class="dots">{dots_r}</div><div class="mut">{c['right_label']} <b>{c['right']}</b></div></div></div>"""
        blocks.append(f"""<div class="wrap"><button class="card" onclick="this.classList.toggle('f')">
          <div class="face front"><div class="t">{c['title']}</div>{front}<div class="hint">tap to see how it was measured</div></div>
          <div class="face back"><div class="t">{c['title']}</div><p>{c['method']}</p><div class="hint">tap to flip back</div></div></button></div>""")
    html = f"""<style>
    body{{margin:0;font-family:Inter,system-ui,sans-serif;color:{INK}}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}}
    .wrap{{height:{height - 30}px;perspective:1200px}} .card{{all:unset;display:block;position:relative;width:100%;height:100%;cursor:pointer;transform-style:preserve-3d;transition:transform .55s}}
    .card.f{{transform:rotateY(180deg)}} .face{{position:absolute;inset:0;border-radius:18px;padding:18px;backface-visibility:hidden;display:flex;flex-direction:column;justify-content:space-between;box-sizing:border-box}}
    .front{{background:#fff;border:1px solid {RULE}}} .back{{background:{FOREST};color:{PAPER};transform:rotateY(180deg)}}
    .t{{font-weight:700;font-size:1.02rem}} .big{{font-family:Fraunces,Georgia,serif;font-weight:300;font-size:2.3rem}} .mut{{color:#6C6C6C;font-size:.85rem}}
    .pill{{display:inline-block;margin-top:4px;background:{FOREST};color:{PAPER};border-radius:999px;padding:2px 9px;font-size:.72rem;font-weight:700}}
    .hint{{font-size:.72rem;opacity:.65}} .back p{{font-size:.86rem;line-height:1.45;opacity:.92}}
    .bar{{margin-top:6px}} .lbl{{display:flex;justify-content:space-between;font-size:.82rem}} .track{{height:12px;background:#F1EEE6;border-radius:9px;margin-top:3px}}
    .fill{{height:100%;width:0;border-radius:9px;transition:width .9s cubic-bezier(.2,.7,.2,1)}}
    .dots{{display:flex;flex-wrap:wrap;gap:4px;max-width:9rem}} .dots i{{width:12px;height:12px;border-radius:50%;opacity:0;transform:scale(0);transition:all .3s ease}}
    .sweep{{transition:stroke-dashoffset 1.1s cubic-bezier(.2,.7,.2,1)}}
    </style><div class="grid">{''.join(blocks)}</div>
    <script>setTimeout(()=>{{document.querySelectorAll('.sweep').forEach(c=>c.style.strokeDashoffset=c.dataset.to);
    document.querySelectorAll('.fill').forEach(f=>f.style.width=f.dataset.w+'%');
    document.querySelectorAll('.dots i').forEach(d=>{{d.style.opacity=1;d.style.transform='scale(1)'}});}},80);</script>{AUTOSIZE}"""
    rows = (len(cards) + 2) // 3
    components.html(html, height=height * rows)


def checklist(items: list[tuple[str, str, str]]) -> None:
    """items: (status ok|bad|warn, title, detail) -> staggered animated list."""
    icon = {"ok": ("✓", FOREST), "bad": ("✕", RED), "warn": ("?", AMBER)}
    html = ""
    for i, (s, t, d) in enumerate(items):
        ch, col = icon[s]
        html += (f"<div class='ao-check' style='animation-delay:{i * 70}ms'><span style='background:{col};color:#fff;"
                 f"border-radius:50%;min-width:24px;height:24px;display:inline-flex;align-items:center;justify-content:center;"
                 f"font-weight:700'>{ch}</span><div><b>{t}</b><div class='ao-muted'>{d}</div></div></div>")
    st.markdown(html, unsafe_allow_html=True)


def pill(text: str, kind: str = "ok") -> str:
    return f"<span class='ao-pill ao-{kind}'>{text}</span>"


class Timer:
    def __init__(self, key: str):
        self.key = f"timer_{key}"
        if self.key not in st.session_state:
            st.session_state[self.key] = time.time()

    def reset(self):
        st.session_state[self.key] = time.time()

    @property
    def seconds(self) -> float:
        return round(time.time() - st.session_state[self.key], 1)
