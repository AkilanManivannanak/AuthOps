from datetime import datetime

import streamlit as st

from app.account import acct, open_page, role, today, ws
from app.nextup import next_up
from app.ui import asset_json, setup
from authops import workspace as W

first = (acct().get("name") or "there").split()[0]
try:   # the visitor's own clock, not the server's
    from zoneinfo import ZoneInfo
    hour = datetime.now(ZoneInfo(st.context.timezone or "America/New_York")).hour
except Exception:
    hour = datetime.now().hour
setup(f"{'Good morning' if hour < 12 else 'Good afternoon' if hour < 18 else 'Good evening'}, {first}")
w, t = ws(), today()

# ------------------------------------------------------------------ patients and families
if role() == "patient":
    next_up("care_readiness")
    st.markdown("### Your letters")
    if not w["letters"]:
        st.markdown("<div class='ao-card' style='text-align:center;padding:36px'><div style='font-family:Fraunces,Georgia,serif;"
                    "font-size:1.4rem'>No letters yet</div><div class='ao-muted'>Read your first insurance letter and it "
                    "will be kept here with its deadline.</div></div>", unsafe_allow_html=True)
    tone = {"approved": ("#5B2A86", "APPROVED"), "partially approved": ("#B4532F", "PARTLY APPROVED"), "denied": ("#C0446A", "DENIED")}
    for L in w["letters"]:
        col, word = tone.get((L.get("decision") or "").lower(), ("#6E5C76", (L.get("decision") or "LETTER").upper()))
        st.markdown(f"<div class='ao-card'><span style='border:3px solid {col};color:{col};border-radius:10px;padding:2px 10px;"
                    f"font-weight:800;letter-spacing:.1em;font-size:.8rem'>{word}</span> &nbsp; <b>{L.get('service') or ''}</b>"
                    f"<div style='margin-top:8px'>{L.get('summary') or ''}</div><div class='ao-muted' style='margin-top:6px'>"
                    f"{'Appeal deadline: ' + L['deadline'] if L.get('deadline') else ''} {('· ' + L['start'] + ' to ' + L['end']) if L.get('start') else ''}"
                    f" · read {L.get('read_on', '')}</div></div>", unsafe_allow_html=True)
    if w.get("costs"):
        c = w["costs"][0]
        st.markdown(f"### Your cost estimate\n<div class='ao-card'><span class='ao-big'>{c['total']}</span> for {c['visits']} visits "
                    f"<span class='ao-muted'>(saved {c['on']})</span></div>", unsafe_allow_html=True)
    st.stop()

# ------------------------------------------------------------------ clinics and AI operations
next_up("care_readiness")
st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)
SHORT = {"aba": "ABA", "physical_therapy": "Physical therapy", "behavioral_health": "Behavioral health"}
COLS = [("new", "New documents", ["New document"]), ("action", "Action required", ["Action required", "Denied"]),
        ("ready", "Ready to send", ["Ready to send"]), ("waiting", "Waiting on payor", ["Waiting on payor", "Reauth sent"]),
        ("due", "Reauth due", ["Reauth due"]), ("clear", "Clear for care", ["Clear for care"])]
cards = {k: [] for k, _, _ in COLS}
for p in w["patients"]:
    s = W.status(p, w, t)
    k = next(k for k, _, labels in COLS if s["label"] in labels)
    cards[k].append({"id": p["id"], "name": p["name"], "service": SHORT[p["spec"]], "payor": p["payor_name"].split()[0],
                     "label": s["label"], "detail": s["detail"], "tone": s["tone"]})
m = W.metrics(w, t)
tiles = [{"value": m["action"], "label": "need you today", "tone": "warn" if m["action"] else "", "cols": ["action", "due"]},
         {"value": m["ready"], "label": "ready to send", "tone": "", "cols": ["ready"]},
         {"value": m["waiting"], "label": "waiting on a payor", "tone": "", "cols": ["waiting"]},
         {"value": m["clear"], "label": "cleared for care", "tone": "ok", "cols": ["clear", "due"]}]
from app.widgets.board import board  # noqa: E402

pid = board(tiles, [{"key": k, "label": lab, "cards": cards[k]} for k, lab, _ in COLS], key=f"board_{len(w['activity'])}")
if pid:
    p = W.find(w, pid)
    if p["stage"] in ("approved", "partial"):
        open_page("insurance_monitoring", pid)
    open_page("prior_authorizations", pid, {"tool": "Appeal a denial"} if p["stage"] == "denied" else None)

st.markdown("### Recent activity")
import time as _t  # noqa: E402

for a in w["activity"][:6]:
    ago = max(0, int(_t.time() - a["ts"]))
    when = "just now" if ago < 60 else f"{ago // 60} min ago" if ago < 3600 else f"{ago // 3600} h ago" if ago < 86400 else f"{ago // 86400} d ago"
    st.markdown(f"<div style='display:flex;gap:10px;padding:8px 0;border-bottom:1px solid #F0EAE2'><span style='color:#8C5FB9'>●</span>"
                f"<div style='flex:1;font-size:.9rem'>{a['text']}</div><span class='ao-muted' style='white-space:nowrap'>{when}</span></div>",
                unsafe_allow_html=True)

st.markdown("### The last 26 weeks, with and without AuthOps")
from app.widgets.pulse import pulse  # noqa: E402
from authops.sim.floor import build as build_floor  # noqa: E402

@st.cache_data(show_spinner=False)
def _floor():
    return asset_json("floor.json") or build_floor()

pulse(_floor())
