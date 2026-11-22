import time
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from app.ui import FOREST, RED, setup, store
from authops.ops import userstore as us

setup("Study and evidence",
      "Everything on this page is computed live from what real testers did in the app. Nothing is seeded. "
      "If a number is zero, nobody has done that yet.")

S = store()
if not S.persistent:
    st.warning("Storage is a local SQLite file. On Streamlit Cloud it is wiped on every redeploy, so set "
               "DATABASE_URL (free Neon or Supabase Postgres) in the app secrets before inviting testers.")

testers = pd.DataFrame(S.rows(us.testers))
events = pd.DataFrame(S.rows(us.events))
docs = pd.DataFrame(S.rows(us.doc_labels))
qa = pd.DataFrame(S.rows(us.qa_labels))
tasks = pd.DataFrame(S.rows(us.task_results))
surveys = pd.DataFrame(S.rows(us.surveys))
runs = pd.DataFrame(S.rows(us.agent_runs))

c = st.columns(6)
c[0].metric("Testers (consented)", len(testers))
c[1].metric("Sessions", S.counts()["sessions"])
c[2].metric("Documents reviewed", docs.doc_id.nunique() if len(docs) else 0)
c[3].metric("QA field verdicts", len(qa))
c[4].metric("Live agent runs", len(runs))
c[5].metric("Surveys", len(surveys))

if len(testers):
    st.markdown("#### Who took part")
    st.dataframe(testers.groupby(["role", "experience"]).size().rename("testers").reset_index(),
                 hide_index=True, width="stretch")

if len(events):
    ev = events.copy()
    ev["day"] = pd.to_datetime(ev.ts, unit="s").dt.date.astype(str)
    st.altair_chart(alt.Chart(ev[ev.tester_id.notna()]).mark_bar(color=FOREST).encode(
        x=alt.X("day:N", title=None), y=alt.Y("count():Q", title="actions by testers")).properties(height=180),
        width="stretch")

st.markdown("#### Human vs AI on documents")
if len(docs):
    d = docs[docs.truth_value != "None"].copy()
    if len(d):
        from authops.docintel.evaluate import values_match

        def ok(val, row):
            if val in (None, "None", ""):
                return row.truth_value in ("None", "")
            tv = row.truth_value
            if tv.startswith("["):
                import ast

                return values_match(row.field, [x.strip() for x in str(val).split(",")], ast.literal_eval(tv))
            return values_match(row.field, val, tv)

        d["ai_ok"] = d.apply(lambda r: ok(r.model_value, r), axis=1)
        d["human_ok"] = d.apply(lambda r: ok(r.human_value, r), axis=1)
        k1, k2, k3 = st.columns(3)
        k1.metric("AI field accuracy", f"{d.ai_ok.mean():.1%}")
        k2.metric("Human-corrected accuracy", f"{d.human_ok.mean():.1%}")
        fixed = ((~d.ai_ok) & d.human_ok).sum()
        k3.metric("AI errors fixed by reviewers", f"{fixed} of {(~d.ai_ok).sum()}")
        st.caption(f"Median time per document: {docs.groupby(['tester_id', 'doc_id']).seconds_on_doc.max().median():.0f}s")
else:
    st.caption("No document reviews yet.")

st.markdown("#### QA reviewer quality")
if len(qa):
    qa["right"] = qa.apply(lambda r: (r.verdict in ("correct", "absent")) == (r.auto_verdict in ("correct", "absent")), axis=1)
    k = us.pairwise_kappa(S.rows(us.qa_labels))
    errs = qa[qa.auto_verdict.isin(["wrong", "missing"])]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Verdicts matching ground truth", f"{qa.right.mean():.1%}")
    k2.metric("AI errors caught by reviewers", f"{errs.verdict.isin(['wrong', 'missing']).mean():.0%}" if len(errs) else "n/a")
    k3.metric("Inter-rater kappa", k["mean_kappa"] if k["mean_kappa"] is not None else "n/a", help=f"{k['pairs']} reviewer pairs")
    k4.metric("Median seconds per item", f"{qa.groupby(['tester_id', 'item_id']).seconds_on_item.max().median():.0f}")
    by_field = qa.groupby("field").right.mean().sort_values().reset_index()
    st.altair_chart(alt.Chart(by_field).mark_bar().encode(
        x=alt.X("right:Q", title="reviewer agreement with truth", axis=alt.Axis(format="%")),
        y=alt.Y("field:N", sort="x", title=None),
        color=alt.condition(alt.datum.right < 0.8, alt.value(RED), alt.value(FOREST))).properties(height=320),
        width="stretch")
else:
    st.caption("No QA verdicts yet.")

st.markdown("#### Tasks and usability")
if len(tasks):
    t2 = tasks[tasks.success == 1].groupby("task").tester_id.nunique().rename("testers completed").reset_index()
    st.dataframe(t2, hide_index=True, width="stretch")
if len(surveys):
    s = surveys.sus_score
    ci = 1.96 * s.std(ddof=1) / len(s) ** 0.5 if len(s) > 1 else 0
    st.metric("System Usability Scale (0-100)", f"{s.mean():.1f}", help=f"n={len(s)}, 95% CI ±{ci:.1f}. 68 is average.")
    comments = surveys[surveys.comment.str.len() > 0].comment.tolist()
    for cm in comments[-5:]:
        st.markdown(f"> {cm}")

st.markdown("#### Claim builder")
st.caption("The only sentence you should put on a resume about usage is one this box generates from the data.")
if len(testers):
    first = datetime.fromtimestamp(testers.created_at.min()).strftime("%b %d, %Y")
    last = datetime.fromtimestamp(events.ts.max()).strftime("%b %d, %Y") if len(events) else first
    parts = [f"{len(testers)} testers ({', '.join(sorted(testers.role.unique()))})"]
    if len(docs):
        parts.append(f"{docs.doc_id.nunique()} documents reviewed")
    if len(qa):
        parts.append(f"{len(qa)} field-level QA verdicts")
        k = us.pairwise_kappa(S.rows(us.qa_labels))
        if k["mean_kappa"] is not None:
            parts.append(f"inter-rater kappa {k['mean_kappa']:.2f}")
    if len(surveys):
        parts.append(f"SUS {surveys.sus_score.mean():.0f}/100 (n={len(surveys)})")
    st.code(f"User-tested by {', '.join(parts)}, {first} to {last}.", language=None)
else:
    st.code("No testers yet. Nothing to claim.", language=None)

with st.expander("Export (study owner)"):
    key = st.text_input("Admin key", type="password")
    admin = None
    try:
        admin = st.secrets.get("ADMIN_KEY")
    except Exception:
        pass
    if admin and key == admin:
        for name, df in [("testers", testers), ("events", events), ("doc_labels", docs), ("qa_labels", qa),
                         ("tasks", tasks), ("surveys", surveys), ("agent_runs", runs)]:
            st.download_button(f"{name}.csv", df.to_csv(index=False), f"{name}_{int(time.time())}.csv")
    elif key:
        st.error("Wrong key.")
