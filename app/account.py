"""Accounts, the role a person picked, and their workspace. Every page reads and writes the same workspace."""
from __future__ import annotations

import random
from datetime import date

import streamlit as st

from authops import workspace as W

ROLES = {
    "patient": ("I'm a patient or family member", "Understand an insurance letter, know your deadlines, estimate your costs."),
    "clinic": ("I work at a clinic", "Get prior authorizations approved the first time and keep care from lapsing."),
    "ops": ("I run AI operations", "Review what the AI read, approve payor rule changes, keep the agents healthy."),
}


def today() -> date:
    return date.today()


def _store():
    from app.ui import store
    return store()


def acct() -> dict | None:
    return st.session_state.get("acct")


def ws() -> dict:
    return st.session_state["ws"]


def role() -> str:
    a = acct()
    return (a or {}).get("role") or ""


def save(msg: str | None = None) -> None:
    a = acct()
    if a and not a.get("guest"):
        try:
            _store().save_account(a["id"], workspace=st.session_state["ws"])
        except Exception:
            st.toast("Could not save just now; your changes are kept for this visit.")
    if msg:
        st.toast(msg)
        try:   # after every action, point at the next most useful thing to do
            from authops import workspace as W
            nxt = W.suggestions(st.session_state["ws"], today(), 1)
            if nxt:
                st.toast(f"Next: {nxt[0]['title']}", icon="👉")
        except Exception:
            pass


# ------------------------------------------------------------------ stay signed in across reloads
_KEEP_JS = r"""
export default function(component){
 const {data,setTriggerValue}=component;const K="authops_session";
 try{ if(data.set){localStorage.setItem(K,data.set)} else if(data.clear){localStorage.removeItem(K)}
      else {const t=localStorage.getItem(K); if(t) setTriggerValue("token",t); else setTriggerValue("token","none")} }
 catch(e){ setTriggerValue("token","none") }
}
"""
_keeper = st.components.v2.component("authops_keeper", js=_KEEP_JS, html="<span></span>")


def _secret() -> bytes:
    import hashlib
    import os
    return hashlib.sha256(("authops:" + os.environ.get("AUTHOPS_SECRET", "") + os.environ.get("DATABASE_URL", "local")).encode()).digest()


def _token(aid: str) -> str:
    import hashlib
    import hmac
    return aid + "." + hmac.new(_secret(), aid.encode(), hashlib.sha256).hexdigest()[:32]


def _restore() -> bool:
    """Read the browser's saved session once; True once the answer is known."""
    if st.session_state.get("_keep_checked"):
        return True
    res = _keeper(data={}, key="keep_read", on_token_change=lambda: None)
    tok = getattr(res, "token", None)
    if tok is None:
        return False
    st.session_state._keep_checked = True
    if tok != "none" and "." in tok:
        aid = tok.split(".")[0]
        import hmac
        if hmac.compare_digest(tok, _token(aid)):
            got = _store().account(aid)
            if got:
                _start(got, remember=False)
    return True


def _start(a: dict, remember: bool = True) -> None:
    st.session_state.acct = a
    if remember and not a.get("guest"):
        st.session_state._keep_set = _token(a["id"])
    if a.get("workspace") and a.get("role"):
        st.session_state.ws = a["workspace"]


def set_role(r: str) -> None:
    a = acct()
    a["role"] = r
    seed = random.Random(a.get("id", "guest")).randint(1, 10_000)
    st.session_state.ws = W.new_workspace(r, a.get("name", ""), seed=seed, today=today())
    if not a.get("guest"):
        _store().save_account(a["id"], role=r, workspace=st.session_state.ws)


CSS = """<style>
.lp-hero{font-family:Fraunces,Georgia,serif;font-size:clamp(2.4rem,5vw,4rem);line-height:1.02;letter-spacing:-.03em;margin:.6rem 0 .4rem}
.lp-hero em{font-style:normal;background:linear-gradient(100deg,#E98A6E 0%,#8C5FB9 55%,#C77DC8 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
.lp-sub{color:#6E5C76;font-size:1.05rem;max-width:520px}
.rc{border:1px solid #ECE5D8;border-radius:20px;padding:22px;background:#fff;min-height:170px;transition:all .2s}
.rc:hover{border-color:#8C5FB9;box-shadow:0 16px 36px -26px rgba(30,5,37,.6);transform:translateY(-2px)}
.rc .t{font-family:Fraunces,Georgia,serif;font-size:1.35rem;margin-bottom:6px}.rc .d{color:#6E5C76;font-size:.92rem}
.rc .i{font-size:1.6rem;margin-bottom:8px}
</style>"""


def gate() -> None:
    """Sign in, then pick a role. Stops the page until both are done."""
    if "_entry" not in st.session_state:   # remember the page asked for, to return to it after signing in
        try:
            from urllib.parse import urlparse
            st.session_state._entry = urlparse(st.context.url).path.strip("/").split("/")[-1]
        except Exception:
            st.session_state._entry = ""
    if st.session_state.get("_keep_set"):
        _keeper(data={"set": st.session_state.pop("_keep_set")}, key="keep_set")
    if st.session_state.get("_keep_clear"):
        _keeper(data={"clear": True}, key="keep_clear")
        st.session_state._keep_clear = False
    a = acct()
    if a and a.get("role") and "ws" in st.session_state:
        return
    if not a and not _restore():
        st.stop()   # waiting for the browser to say whether a session was saved
    a = acct()
    if a and a.get("role") and "ws" in st.session_state:
        st.rerun()
    from app.ui import CSS as UI_CSS
    st.markdown(UI_CSS + CSS, unsafe_allow_html=True)
    if not a:
        left, right = st.columns([1.15, 1], gap="large")
        left.markdown("<div class='ao-eyebrow'>AuthOps</div><div class='lp-hero'>Care, <em>cleared</em> before it starts.</div>"
                      "<div class='lp-sub'>Prior authorizations, benefit checks and coverage, handled in one place. "
                      "Sign in to pick up where you left off.</div>", unsafe_allow_html=True)
        with right:
            t1, t2 = st.tabs(["Sign in", "Create account"])
            with t1, st.form("signin"):
                em = st.text_input("Email")
                pw = st.text_input("Password", type="password")
                if st.form_submit_button("Sign in", type="primary", width="stretch"):
                    got = _store().sign_in(em, pw)
                    if got:
                        _start(got)
                        st.rerun()
                    st.error("That email and password don't match.")
            with t2, st.form("signup"):
                nm = st.text_input("Your name")
                em2 = st.text_input("Email", key="em2")
                pw2 = st.text_input("Password (8+ characters)", type="password", key="pw2")
                if st.form_submit_button("Create account", type="primary", width="stretch"):
                    try:
                        _start(_store().create_account(em2, nm, pw2))
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
            if st.button("Continue without an account", width="stretch"):
                _start({"id": "guest", "name": "Guest", "role": "", "guest": True})
                st.rerun()
            st.caption("Your account keeps your work between visits. Without one, it lasts until you close the tab.")
        st.stop()
    first = (a.get("name") or "there").split()[0]
    st.markdown(f"<div class='ao-eyebrow'>Welcome, {first}</div><div class='lp-hero' style='font-size:2.6rem'>What brings you here?</div>",
                unsafe_allow_html=True)
    cols = st.columns(3)
    icons = {"patient": "🧾", "clinic": "🩺", "ops": "🧭"}
    for col, (k, (t, d)) in zip(cols, ROLES.items()):
        col.markdown(f"<div class='rc'><div class='i'>{icons[k]}</div><div class='t'>{t}</div><div class='d'>{d}</div></div>",
                     unsafe_allow_html=True)
        if col.button("Continue", key=f"role_{k}", width="stretch", type="primary" if k == "clinic" else "secondary"):
            set_role(k)
            st.rerun()
    st.stop()


def header() -> None:
    """Account chip on every page: who is signed in, the role, switch or sign out."""
    a = acct()
    st.markdown("<style>.st-key-acct_chip{position:fixed;top:12px;right:64px;z-index:999991;width:auto!important}"
                ".st-key-acct_chip button{border-radius:999px;padding:4px 14px;min-height:34px}</style>",
                unsafe_allow_html=True)
    c = st.container(key="acct_chip")
    with c.popover(f"👤 {a.get('name', 'Guest').split()[0]}"):
        st.markdown(f"**{a.get('name')}**  \n{a.get('email', 'Not signed in')}")
        st.caption("Using AuthOps as: " + ROLES[a["role"]][0].replace("I'm ", "").replace("I ", ""))
        new = st.selectbox("Switch view", list(ROLES), index=list(ROLES).index(a["role"]),
                           format_func=lambda k: ROLES[k][0])
        if new != a["role"] and st.button("Switch", width="stretch"):
            set_role(new)
            st.rerun()
        if st.button("Start my workspace over", width="stretch"):
            set_role(a["role"])
            st.rerun()
        if st.button("Sign out", width="stretch"):
            for k in ("acct", "ws", "focus"):
                st.session_state.pop(k, None)
            st.session_state._keep_clear = True
            st.rerun()


def open_page(page: str, pid: str | None = None, params: dict | None = None) -> None:
    if pid:
        st.session_state.focus = pid
    st.switch_page(f"app/views/{page}.py", query_params=params or None)
