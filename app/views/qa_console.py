import random

import pandas as pd
import streamlit as st

from app.ui import ASSETS, Timer, asset_json, log, require_tester, setup, store
from authops.ops.userstore import pairwise_kappa, qa_labels

setup("QA Console",
      "This is the specialist review step. Check each value the AI extracted against the document and mark it. "
      "Your verdicts are scored against ground truth and against other reviewers.")
t = require_tester("to grade items (reviews are tied to a reviewer for agreement scoring)")
items = (asset_json("qa/items.json") or [])
if not items:
    st.warning("No review items. Run scripts/build_app_assets.py.")
    st.stop()

mine = [r for r in store().rows(qa_labels) if t and r["tester_id"] == t["id"]]
done_ids = {r["item_id"] for r in mine}
order = items[:]
random.Random(t["id"] if t else "guest").shuffle(order)
queue_left = [i for i in order if i["item_id"] not in done_ids]

c1, c2, c3 = st.columns(3)
c1.metric("Items in queue", len(queue_left))
c2.metric("You reviewed", len(done_ids))
if mine:
    agree = sum((r["verdict"] in ("correct", "absent")) == (r["auto_verdict"] in ("correct", "absent")) for r in mine)
    c3.metric("Your agreement with ground truth", f"{agree / len(mine):.0%}")

if not queue_left:
    st.success("Queue empty. Thank you. See Study and evidence for how reviewers compare.")
    st.stop()

item = queue_left[0]
timer = Timer(f"qa_{item['item_id']}")
left, right = st.columns([1.05, 1])
with left:
    st.image(str(ASSETS / "qa" / item["image"]), use_container_width=True)
    st.caption(f"{item['doc_type'].replace('_', ' ')} · {item['condition']} image · item {item['item_id']}")
with right:
    st.markdown("#### What the AI extracted")
    verdicts = {}
    with st.form(f"qa_{item['item_id']}"):
        for f in item["fields"]:
            label = f["field"].replace("_", " ")
            val = f["value"]
            shown = "(left blank)" if val is None else (", ".join(val) if isinstance(val, list) else str(val))
            opts = (["correct", "wrong"] if val is not None else ["absent", "missing"])
            help_txt = ("correct: matches the page · wrong: differs from the page" if val is not None else
                        "absent: the page has no such value · missing: the page shows it, the AI should have filled it")
            verdicts[f["field"]] = st.radio(f"**{label}**: `{shown}`", opts, horizontal=True, index=None,
                                            key=f"v_{item['item_id']}_{f['field']}", help=help_txt)
        comment = st.text_input("Comment (optional)")
        submitted = st.form_submit_button("Submit review", type="primary", use_container_width=True, disabled=t is None)
    if submitted:
        if any(v is None for v in verdicts.values()):
            st.error("Give every field a verdict.")
        else:
            secs = timer.seconds
            for f in item["fields"]:
                store().qa_label(tester_id=t["id"], item_id=item["item_id"], field=f["field"],
                                 verdict=verdicts[f["field"]], comment=comment[:500], auto_verdict=f["auto_verdict"],
                                 seconds_on_item=secs)
            log("qa_review", {"item": item["item_id"], "seconds": secs})
            if len(done_ids) + 1 >= 5:
                store().task(tester_id=t["id"], task="qa_review", success=1, seconds=secs, detail=f"{len(done_ids) + 1} items")
            right_n = sum((verdicts[f["field"]] in ("correct", "absent")) == (f["auto_verdict"] in ("correct", "absent"))
                          for f in item["fields"])
            st.toast(f"Saved. {right_n}/{len(item['fields'])} verdicts match ground truth.")
            st.rerun()

st.markdown("### Reviewer agreement so far")
all_labels = store().rows(qa_labels)
if all_labels:
    df = pd.DataFrame(all_labels)
    df["matches_truth"] = df.apply(lambda r: (r.verdict in ("correct", "absent")) == (r.auto_verdict in ("correct", "absent")), axis=1)
    k = pairwise_kappa(all_labels)
    a, b, c = st.columns(3)
    a.metric("Reviewers", df.tester_id.nunique())
    b.metric("Field verdicts", len(df))
    c.metric("Mean pairwise Cohen's kappa", "needs 2 reviewers on 5+ shared fields" if k["mean_kappa"] is None else k["mean_kappa"])
    caught = df[(df.auto_verdict.isin(["wrong", "missing"]))]
    if len(caught):
        st.caption(f"AI errors in reviewed items: {len(caught)}. Caught by reviewers: "
                   f"{(caught.verdict.isin(['wrong', 'missing'])).mean():.0%}.")
else:
    st.caption("No reviews yet.")
