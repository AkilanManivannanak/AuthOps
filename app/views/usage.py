import pandas as pd
import streamlit as st

from app.ui import FOREST, setup, store
from authops.analytics.reports import TITLES, run, sql

setup("Usage and quality", "Real use of this app, by role, and where people said the AI was wrong.")
s = store()

funnel = run("funnel", s)
cols = st.columns(len(funnel))
top = funnel[0]["sessions"] or 0
for c, r in zip(cols, funnel):
    pct = f"{100 * r['sessions'] / top:.0f}% of visits" if top else "no visits yet"
    c.metric(r["stage"], r["sessions"], pct, delta_color="off")
if not top:
    st.info("Nothing recorded yet. Every visit, tool used and rating lands here as it happens; nothing is pre-filled.")
st.caption("Counted from this deployment's database" + ("." if s.persistent else
           " (a local file on this server, which resets when the app redeploys; set DATABASE_URL to keep it)."))

a, b = st.columns(2)
with a:
    st.markdown("#### " + TITLES["by_role"])
    br = pd.DataFrame(run("by_role", s))
    br.columns = [c.capitalize() for c in br.columns]
    st.dataframe(br, hide_index=True, width="stretch")
with b:
    st.markdown("#### " + TITLES["daily"])
    d = pd.DataFrame(run("daily", s))
    if len(d):
        st.bar_chart(d.set_index("day")[["sessions"]], height=200, color=FOREST)
    else:
        st.caption("No days yet.")



def table(name: str, empty: str) -> None:
    st.markdown("#### " + TITLES[name])
    df = pd.DataFrame(run(name, s))
    df.columns = [c.replace("pct_", "% ").replace("_", " ").capitalize() for c in df.columns]
    if len(df):
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        st.caption(empty)


table("ai_accuracy", "No ratings yet. People rate answers with 'Was this right?' under each result in Check a document.")
table("what_went_wrong", "Nothing marked wrong yet.")
table("field_errors", "No review-queue verdicts yet.")

wrong = [r for r in s.rows(__import__("authops.ops.userstore", fromlist=["feedback"]).feedback) if r["verdict"] == "wrong"]
if wrong:
    st.markdown("#### Look at an answer someone marked wrong")
    pick = st.selectbox("Rating", range(len(wrong)), format_func=lambda i: (
        f"{wrong[i]['day']} · {wrong[i]['kind']} · {wrong[i]['what'] or 'not said'} · "
        f"{'sample' if wrong[i].get('is_sample') else 'real upload'} · document {wrong[i].get('doc_id') or 'n/a'}"))
    r = wrong[pick]
    if r.get("comment"):
        st.markdown(f"**They said it should be:** {r['comment']}")
    st.json(__import__("json").loads(r["result"]) if r.get("result") else {"result": "not recorded (rated before Nov 26)"})

with st.expander("The SQL behind these numbers"):
    q = st.selectbox("Report", list(TITLES), format_func=TITLES.get)
    st.code(sql(q), language="sql")
    st.dataframe(pd.DataFrame(run(q, s)), hide_index=True, width="stretch")
