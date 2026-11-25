"""Shared look, components and tester identity for the AuthOps app.

Design language follows Silna's brand: white and cream surfaces, plum ink, violet for "earned/working",
rose for "failed/at risk", a peach-violet-pink dawn accent, serif light display figures, numbers that count up,
rings and bars that sweep in once, cards that flip to show how a number was measured.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "app" / "assets"
from app.tokens import PALETTE as _P  # noqa: E402

FOREST, GREEN, RED, INK, RULE, PAPER, TAG, AMBER = (
    _P["violet"], _P["lilac"], _P["rose"], _P["ink"], _P["sand"], _P["cream"], _P["tag"], _P["amber"])

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400&family=DM+Sans:wght@400;500;600;700&display=swap');
html, body, [class*="css"], .stMarkdown, p, li, label, input, textarea, button {{ font-family: 'DM Sans', system-ui, sans-serif; }}
h1, h2, h3 {{ font-family: 'Fraunces', Georgia, serif !important; font-weight: 400 !important; letter-spacing: -0.025em; color: {INK}; }}
h1 {{ font-size: 3rem !important; line-height: 1.05 !important; }}
.block-container {{ padding-top: 2.2rem; max-width: 1280px; }}
.ao-sub {{ color: #7A6B80; font-size: 1.02rem; margin-top: -0.6rem; margin-bottom: 1.4rem; max-width: 760px; }}
.ao-tile {{ border: 1px solid {RULE}; background: #fff; border-radius: 18px; padding: 18px 20px; transition: all .18s ease; height: 100%; }}
.ao-tile:hover {{ transform: translateY(-2px); box-shadow: 0 8px 24px rgba(31,42,36,.10); border-color: {FOREST}; }}
.ao-tile.hot {{ background: {TAG}; border-color: {INK}; }}
.ao-fig {{ font-family: 'Fraunces', Georgia, serif; font-weight: 300; font-size: clamp(1.9rem, 3.4vw, 2.9rem); line-height: 1; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.ao-lab {{ margin-top: 8px; font-size: .9rem; color: #444; }}
.ao-pill {{ display:inline-block; border-radius: 999px; padding: 2px 10px; font-size: .78rem; font-weight: 700; }}
.ao-ok {{ background: {FOREST}; color: {PAPER}; }} .ao-bad {{ background: {RED}; color: #fff; }} .ao-warn {{ background: {AMBER}; color: #fff; }}
.ao-muted {{ color: #7A6B80; font-size: .88rem; }}
.ao-card {{ border:1px solid {RULE}; background:#fff; border-radius: 16px; padding: 16px 18px; margin-bottom: 10px; }}
.ao-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin-bottom:.6rem; }}
.ao-rise {{ animation: aoIn .45s ease both; }}
.ao-big {{ font-family:'Fraunces',Georgia,serif; font-weight:300; font-size:2.1rem; line-height:1.1; }}
.ao-track {{ height:10px; background:#F7F0EC; border-radius:9px; margin-top:3px; overflow:hidden; }}
.ao-fill {{ height:100%; width:var(--w); border-radius:9px; animation: aoGrow .9s cubic-bezier(.2,.7,.2,1) both; }}
@keyframes aoGrow {{ from {{ width:0; }} to {{ width:var(--w); }} }}
.ao-sweep {{ stroke-dashoffset:var(--to); animation: aoSweep 1.1s cubic-bezier(.2,.7,.2,1) both; }}
@keyframes aoSweep {{ from {{ stroke-dashoffset:var(--from); }} to {{ stroke-dashoffset:var(--to); }} }}
.ao-dots {{ display:flex; flex-wrap:wrap; gap:4px; max-width:9rem; }}
.ao-dots i {{ width:12px; height:12px; border-radius:50%; animation: aoPop .3s ease both; }}
@keyframes aoPop {{ from {{ opacity:0; transform:scale(0); }} to {{ opacity:1; transform:none; }} }}
.ao-check {{ display:flex; gap:10px; align-items:flex-start; padding:8px 0; border-bottom:1px solid {RULE}; animation: aoIn .35s ease both; }}
@keyframes aoIn {{ from {{ opacity:0; transform: translateY(6px); }} to {{ opacity:1; transform:none; }} }}
div[data-testid="stMetricValue"] {{ font-family: 'Fraunces', Georgia, serif; font-weight: 300; }}
section[data-testid="stSidebar"] {{ background: #F7F0EC; }}
.stButton>button, .stDownloadButton>button, .stFormSubmitButton>button {{ border-radius: 999px; font-weight: 600; padding: .45rem 1.2rem; }}
.stButton>button[kind="primary"], .stFormSubmitButton>button {{ background: #1E0525; border-color: #1E0525; color: #fff; }}
.stButton>button[kind="primary"]:hover {{ background: #32073E; border-color: #32073E; }}
.ao-eyebrow {{ font-size: .74rem; letter-spacing: .14em; text-transform: uppercase; color: #8E8292; font-weight: 500; }}
[data-testid="stSidebarNav"] a span {{ font-weight: 500; }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{ background: #FAE8E8; border-radius: 10px; }}
hr {{ border-color: #ECE5D8 !important; }}
div[data-testid="stAlert"] {{ border-radius: 14px; }}
div[data-testid="stAlertContentInfo"], div[data-testid="stAlertContentSuccess"] {{ color: #1E0525; }}
div[data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]) > div {{ background: #F5EEFB !important; }}
div[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) > div {{ background: #EFE7FA !important; }}
div[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) > div {{ background: #FFF1EA !important; }}
div[data-testid="stAlert"]:has([data-testid="stAlertContentError"]) > div {{ background: #FBEAF1 !important; }}
div[data-testid="stAlert"] a, div[data-testid="stAlert"] strong {{ color: #5B2A86; }}
div[data-testid="stExpander"] details {{ border-radius: 14px; border-color: #ECE5D8; }}
div[data-testid="stPopover"] button {{ border-radius: 999px; }}
.stTabs [data-baseweb="tab"] {{ font-weight: 600; }}
header[data-testid="stHeader"] {{ background: rgba(255,255,255,.92); backdrop-filter: blur(8px); border-bottom: 1px solid #F0EAE2; }}
header[data-testid="stHeader"] a {{ font-weight: 500; }}
.ao-foot {{ margin-top: 3.5rem; padding-top: 1rem; border-top: 1px solid #F0EAE2; color: #8E8292; font-size: .8rem; line-height: 1.5; }}
div[data-testid="stSegmentedControl"] button {{ border-radius: 999px !important; }}
</style>
"""


def setup(title: str, purpose: str = "") -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    if st.session_state.get("_embedded"):   # shown inside a parent page, which has its own heading
        log("view", {"title": title})
        return
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
    return tester()


# ------------------------------------------------------------------ components

def note(text: str, label: str = "ⓘ How this works") -> None:
    """Long explanations live behind a small popover instead of on the page."""
    with st.popover(label):
        st.markdown(text)


def _fmt(value, fmt: str) -> str:
    if fmt == "pct":
        return f"{value * 100:.1f}".removesuffix(".0") + "%"
    if fmt == "pct0":
        return f"{round(value * 100)}%"
    if fmt == "f1":
        return f"{value:.1f}"
    return f"{int(round(value)):,}"


def tiles(items: list[tuple]) -> None:
    """items: (value, label, fmt, hot). Native HTML grid: wraps to fit any screen, no iframe."""
    cells = "".join(
        f"<div class='ao-tile ao-rise {'hot' if hot else ''}' style='animation-delay:{i * 70}ms'>"
        f"<div class='ao-fig'>{_fmt(value, fmt)}</div><div class='ao-lab'>{label}</div></div>"
        for i, (value, label, fmt, hot) in enumerate(items))
    st.markdown(f"<div class='ao-grid'>{cells}</div>", unsafe_allow_html=True)


def _card_front(c: dict) -> str:
    if c["kind"] == "ring":
        share = c["k"] / c["n"] if c["n"] else 0
        r, circ = 46, 2 * 3.14159 * 46
        note = f"<span class='ao-pill ao-ok'>{c['note']}</span>" if c.get("note") else ""
        return (f"<div style='display:flex;gap:14px;align-items:center'>"
                f"<svg viewBox='0 0 112 112' width='96' height='96'><circle cx='56' cy='56' r='{r}' fill='none' "
                f"stroke='{RULE}' stroke-width='11'/><circle class='ao-sweep' cx='56' cy='56' r='{r}' fill='none' "
                f"stroke='{FOREST}' stroke-width='11' stroke-linecap='round' stroke-dasharray='{circ:.1f}' "
                f"style='--from:{circ:.1f};--to:{circ * (1 - share):.1f}' transform='rotate(-90 56 56)'/></svg>"
                f"<div><div class='ao-big'>{share * 100:.1f}%</div><div class='ao-muted'>{c['k']:,} of {c['n']:,}</div>"
                f"{note}</div></div>")
    if c["kind"] == "versus":
        mx = max(c["left"], c["right"]) or 1
        col = FOREST if c.get("good", True) else RED
        bar = lambda lab, v, colr, b: (f"<div style='margin-top:8px'><div style='display:flex;justify-content:space-between;"  # noqa: E731
                                       f"font-size:.82rem'><span>{'<b>' + lab + '</b>' if b else lab}</span><b>{v}</b></div>"
                                       f"<div class='ao-track'><div class='ao-fill' style='--w:{v / mx * 100:.1f}%;"
                                       f"background:{colr}'></div></div></div>")
        return (f"<div class='ao-big' style='color:{col}'>{c['headline']}</div>"
                + bar(c["left_label"], c["left"], "#B3A7B8", False) + bar(c["right_label"], c["right"], col, True))
    dots = lambda n, colr: "".join(f"<i style='background:{colr};animation-delay:{j * 35}ms'></i>" for j in range(n))  # noqa: E731
    return (f"<div style='display:grid;grid-template-columns:1fr auto 1fr;gap:10px;align-items:center'>"
            f"<div><div class='ao-dots'>{dots(c['left'], RED)}</div><div class='ao-muted'>{c['left_label']} "
            f"<b>{c['left']}</b></div></div><div class='ao-muted' style='font-size:.95rem'>vs</div><div><div class='ao-dots'>"
            f"{dots(c['right'], FOREST)}</div><div class='ao-muted'>{c['right_label']} <b>{c['right']}</b></div></div></div>")


def proof_cards(cards: list[dict], height: int = 300) -> None:
    """Result cards with an animated figure and a 'How it was measured' popover. Native, so they stack on phones."""
    for row in range(0, len(cards), 3):
        cols = st.columns(3)
        for col, c in zip(cols, cards[row:row + 3]):
            with col.container(border=True):
                st.markdown(f"<div class='ao-rise'><div style='font-weight:700;margin-bottom:10px'>{c['title']}</div>"
                            f"{_card_front(c)}</div>", unsafe_allow_html=True)
                with st.popover("How it was measured", width="stretch"):
                    st.write(c["method"])


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


def run_view(path: str) -> None:
    """Run an existing view script inside the current page, without its own page heading."""
    import runpy

    st.session_state["_embedded"] = True
    try:
        runpy.run_path(str(ROOT / path), run_name="__main__")
    finally:
        st.session_state["_embedded"] = False


def switch(options: dict, key: str) -> str:
    """Pill switch between the tools on a page; the choice is kept in the URL so links can open a tool."""
    names = list(options)
    want = st.query_params.get(key)
    if key not in st.session_state:
        st.session_state[key] = want if want in names else names[0]
    pick = st.segmented_control("View", names, key=key, label_visibility="collapsed") or names[0]
    if st.query_params.get(key) != pick:
        st.query_params[key] = pick
    return pick


def footer() -> None:
    st.markdown("<div class='ao-foot'>AuthOps is an independent portfolio project by Akilan Manivannan, built for the "
                "Silna Health AI Deployment Analyst application. Not affiliated with or endorsed by Silna Health. "
                "Synthetic patients and fictional payors only; do not enter real patient information.</div>",
                unsafe_allow_html=True)


def rule_label(rule: str) -> str:
    """Payor rule ids as people say them: icd10_billable -> ICD-10 billable."""
    words = {"icd10": "ICD-10", "cpt": "CPT", "npi": "NPI", "id": "ID", "aba": "ABA", "pt": "PT"}
    out = [words.get(w, w) for w in rule.split("_")]
    out[0] = out[0] if out[0].isupper() or "-" in out[0] else out[0].capitalize()
    return " ".join(out)
