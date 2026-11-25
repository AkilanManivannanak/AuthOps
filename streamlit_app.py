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
pages = [
    st.Page(V + "care_readiness.py", title="Care readiness", default=True, url_path="care_readiness"),
    st.Page(V + "try_it.py", title="Try it on your document", url_path="try_it"),
    st.Page(V + "prior_authorizations.py", title="Prior authorizations", url_path="prior_authorizations"),
    st.Page(V + "benefit_checks.py", title="Benefit checks", url_path="benefit_checks"),
    st.Page(V + "insurance_monitoring.py", title="Insurance monitoring", url_path="insurance_monitoring"),
    st.Page(V + "ai_ops_desk.py", title="AI Ops desk", url_path="ai_ops_desk"),
    st.Page(V + "measured.py", title="How it was measured", url_path="how_it_was_measured"),
]
if st.query_params.get("owner") == "1":   # tester study tools, never shown to visitors
    pages += [st.Page(V + "join.py", title="Join the study", url_path="join"),
              st.Page(V + "study.py", title="Study", url_path="study")]
nav = st.navigation(pages, position="top")
st.session_state.page = nav.title
nav.run()

from app.ui import footer  # noqa: E402

footer()
