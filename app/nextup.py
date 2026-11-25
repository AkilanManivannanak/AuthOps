"""'Next up': the one to three things this person should do now, from the shared workspace."""
from __future__ import annotations

import streamlit as st

from app.account import open_page, today, ws
from authops import workspace as W


def next_up(page: str | None = None, limit: int = 3, title: str = "Next up") -> None:
    items = [s for s in W.suggestions(ws(), today(), 8) if s["page"] != page or s.get("pid")][:limit]
    if not items:
        st.markdown("<div class='ao-card' style='background:#F7F1FB;border-color:#E3D6F2'>✓ Nothing waiting. "
                    "Everything is sent, decided or on track.</div>", unsafe_allow_html=True)
        return
    st.markdown(f"<div class='ao-eyebrow' style='margin-bottom:6px'>{title}</div>", unsafe_allow_html=True)
    cols = st.columns(len(items))
    for i, (c, s) in enumerate(zip(cols, items)):
        hot = i == 0
        c.markdown(f"<div class='ao-card' style='min-height:118px;{'background:linear-gradient(135deg,#FDF8F3,#FAE8E8);border-color:#E9C6CF' if hot else ''}'>"
                   f"<div style='font-weight:600;font-size:1rem'>{s['title']}</div><div class='ao-muted'>{s['body']}</div></div>",
                   unsafe_allow_html=True)
        if c.button(s["cta"] + " →", key=f"nx_{page}_{i}_{s.get('pid', '')}", type="primary" if hot else "secondary",
                    width="stretch"):
            open_page(s["page"], s.get("pid"), s.get("params"))
