"""AuthOps app entry point.  Run: streamlit run streamlit_app.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="AuthOps: prior-auth agent operations", page_icon="🩺", layout="wide",
                   initial_sidebar_state="expanded")

V = "app/views/"
pages = {
    "Overview": [
        st.Page(V + "home.py", title="Command center", icon="🧭", default=True),
        st.Page(V + "join.py", title="Join the study", icon="🙋"),
    ],
    "Work the queue": [
        st.Page(V + "document_lab.py", title="Document Lab", icon="📄"),
        st.Page(V + "denial_shield.py", title="Denial Shield", icon="🛡️"),
        st.Page(V + "agent_theater.py", title="Agent Theater", icon="🤖"),
        st.Page(V + "qa_console.py", title="QA Console", icon="✅"),
    ],
    "Operate and improve": [
        st.Page(V + "autonomy_ramp.py", title="Autonomy Ramp", icon="📈"),
        st.Page(V + "playbook_studio.py", title="Playbook Studio", icon="📝"),
        st.Page(V + "phone_agent.py", title="Phone Agent", icon="📞"),
        st.Page(V + "channels.py", title="FHIR and channels", icon="🔀"),
    ],
    "Evidence": [
        st.Page(V + "study.py", title="Study and evidence", icon="📊"),
        st.Page(V + "method.py", title="Method and limits", icon="🔍"),
    ],
}
nav = st.navigation(pages)
st.session_state.page = nav.title

with st.sidebar:
    t = st.session_state.get("tester")
    if t:
        st.markdown(f"**Signed in as** {t['name']}  \n<span style='color:#6C6C6C'>{t['role']}</span>",
                    unsafe_allow_html=True)
        if st.button("Sign out", use_container_width=True):
            st.session_state.pop("tester", None)
            st.rerun()
    else:
        st.markdown("You're exploring as a guest. **Join the study** to have your reviews counted.")
    st.caption("Synthetic patients and fictional payors only. Do not enter real PHI.")

nav.run()
