import streamlit as st

from app.ui import log, setup, store, tester
from authops.ops.userstore import task_results

setup("Join the tester study",
      "Five short tasks, about 20 minutes. Your reviews become the human labels the system is measured against.")

CONSENT = """**What is collected:** the name or handle you enter, your role and experience level, every review and
correction you submit, task completion times, which pages you open, and your survey answers.
**What it is used for:** measuring how well the AI's output holds up under human review (agreement between
reviewers, error catch rates, usability). Results are reported only in aggregate (counts, rates, averages).
**What is not collected:** no email, no real patient data; every document here is synthetic.
You can stop at any time. Ask the study owner to delete your rows and they will be removed."""

TASKS = [
    ("doc_review", "Document Lab", "Review and correct 3 AI-read documents"),
    ("qa_review", "QA Console", "Grade 5 extraction results field by field"),
    ("agent_diagnosis", "Agent Theater", "Run a live agent with chaos on, then diagnose the failed replay"),
    ("drift_hunt", "Denial Shield", "Find a request the rules pass but the payor denies"),
    ("sus", "This page", "Answer the 10-question usability survey"),
]

t = tester()
if not t:
    with st.form("join"):
        name = st.text_input("Name or handle (shown only to the study owner)", max_chars=60)
        role = st.selectbox("Your role", ["Software engineer", "ML / AI engineer", "Data scientist / analyst",
                                          "Healthcare operations / RCM", "Clinician", "Product / design", "Student", "Other"])
        exp = st.select_slider("Years of professional experience", ["0-1", "2-3", "4-6", "7-10", "10+"])
        st.markdown(CONSENT)
        ok = st.checkbox("I understand and agree to take part.")
        if st.form_submit_button("Join", type="primary"):
            if not name.strip() or not ok:
                st.error("Enter a name and tick the consent box.")
            else:
                tid = store().register(name, role, exp)
                st.session_state.tester = {"id": tid, "name": name.strip(), "role": role}
                st.session_state.pop("sid", None)
                log("joined", {"role": role, "experience": exp})
                st.rerun()
    st.stop()

st.success(f"Signed in as **{t['name']}**. Work through the tasks in any order.")
done = {r["task"] for r in store().rows(task_results) if r["tester_id"] == t["id"] and r["success"]}
for key, where, what in TASKS:
    mark = "✅" if key in done else "⬜"
    st.markdown(f"{mark} **{what}**  <span class='ao-muted'>({where})</span>", unsafe_allow_html=True)
st.progress(len(done & {k for k, _, _ in TASKS}) / len(TASKS))

st.markdown("### Usability survey (System Usability Scale)")
ITEMS = ["I think that I would like to use this system frequently.",
         "I found the system unnecessarily complex.",
         "I thought the system was easy to use.",
         "I think that I would need the support of a technical person to be able to use this system.",
         "I found the various functions in this system were well integrated.",
         "I thought there was too much inconsistency in this system.",
         "I would imagine that most people would learn to use this system very quickly.",
         "I found the system very cumbersome to use.",
         "I felt very confident using the system.",
         "I needed to learn a lot of things before I could get going with this system."]
if "sus" in done:
    st.info("Thanks, your survey is recorded.")
else:
    with st.form("sus"):
        answers = [st.radio(q, [1, 2, 3, 4, 5], index=None, horizontal=True, key=f"sus{i}",
                            captions=["Strongly disagree", "", "", "", "Strongly agree"]) for i, q in enumerate(ITEMS)]
        comment = st.text_area("What would make this more useful for a prior-auth operations team?")
        if st.form_submit_button("Submit survey", type="primary"):
            if any(a is None for a in answers):
                st.error("Please answer all 10 statements.")
            else:
                from authops.ops.userstore import sus_score

                s = sus_score(answers)
                store().survey(tester_id=t["id"], sus_score=s, answers=str(answers), comment=comment[:2000])
                store().task(tester_id=t["id"], task="sus", success=1, seconds=0, detail=str(s))
                log("sus_submitted", {"score": s})
                st.success(f"Recorded. Your SUS score: {s:.0f} / 100")
                st.rerun()
