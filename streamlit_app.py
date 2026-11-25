"""AuthOps app entry point.  Run: streamlit run streamlit_app.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="AuthOps: care readiness operations", page_icon="🩺", layout="wide",
                   initial_sidebar_state="collapsed")

try:   # Streamlit secrets -> environment, so the AI reader finds the key on the hosted app
    import os

    for _k in ("ANTHROPIC_API_KEY", "AUTHOPS_MODEL"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:
    pass

V = "app/views/"
from app.account import gate, header, role  # noqa: E402

gate()
r = role()
P = {
    "home": lambda t: st.Page(V + "care_readiness.py", title=t, default=True, url_path="care_readiness"),
    "try": lambda t: st.Page(V + "try_it.py", title=t, url_path="try_it"),
    "pa": lambda t: st.Page(V + "prior_authorizations.py", title=t, url_path="prior_authorizations"),
    "bc": lambda t: st.Page(V + "benefit_checks.py", title=t, url_path="benefit_checks"),
    "im": lambda t: st.Page(V + "insurance_monitoring.py", title=t, url_path="insurance_monitoring"),
    "ops": lambda t: st.Page(V + "ai_ops_desk.py", title=t, url_path="ai_ops_desk"),
    "how": lambda t: st.Page(V + "measured.py", title=t, url_path="how_it_was_measured"),
}
MENU = {   # each role sees only the pages it needs, named the way that person would say it
    "patient": [("home", "My care"), ("try", "Read a letter"), ("bc", "My costs"), ("how", "How it works")],
    "clinic": [("home", "Today"), ("pa", "Prior authorizations"), ("bc", "Benefit checks"),
               ("im", "Insurance monitoring"), ("try", "Check a document"), ("ops", "AI Ops desk"),
               ("how", "How it was measured")],
    "ops": [("home", "Today"), ("ops", "AI Ops desk"), ("im", "Insurance monitoring"), ("pa", "Prior authorizations"),
            ("try", "Check a document"), ("how", "How it was measured")],
}
pages = [P[k](t) for k, t in MENU[r]]
if st.query_params.get("owner") == "1":   # tester study tools, never shown to visitors
    pages += [st.Page(V + "join.py", title="Join the study", url_path="join"),
              st.Page(V + "study.py", title="Study", url_path="study")]
nav = st.navigation(pages, position="top")
_entry = st.session_state.pop("_entry", "")
if _entry and _entry != nav.url_path:
    _want = next((pg for pg in pages if pg.url_path == _entry), None)
    if _want is not None:
        st.switch_page(_want)
st.session_state.page = nav.title
header()
nav.run()

from app.ui import footer  # noqa: E402

footer()
