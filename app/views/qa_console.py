import random

import pandas as pd
import streamlit as st

from app.ui import ASSETS, Timer, asset_json, log, require_tester, setup, store
from authops.ops.userstore import pairwise_kappa, qa_labels

setup("QA Console", "Grade what the AI extracted. Your verdicts are scored against the truth and other reviewers.")
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
from app.widgets.deck import review_deck  # noqa: E402

fields = [{"field": f["field"], "label": f["field"].replace("_", " "), "conf": float(f.get("conf") or 0),
           "value": None if f["value"] is None else (", ".join(f["value"]) if isinstance(f["value"], list) else str(f["value"]))}
          for f in item["fields"]]
sub = review_deck(ASSETS / "qa" / item["image"], fields,
                  f"{item['doc_type'].replace('_', ' ')} · {item['condition']} image", can_save=t is not None,
                  key=f"deck_{item['item_id']}")
if sub:
    verdicts, comment = sub.get("verdicts", {}), sub.get("comment", "")
    if len(verdicts) < len(item["fields"]):
        st.error("Give every field a verdict.")
    else:
        right_n = sum((verdicts[f["field"]] in ("correct", "absent")) == (f["auto_verdict"] in ("correct", "absent"))
                      for f in item["fields"])
        if t is None:
            st.session_state.qa_pending = {"item": item["item_id"], "verdicts": verdicts, "comment": comment}
            st.success(f"{right_n} of {len(item['fields'])} of your verdicts match the truth.")
        else:
            secs = timer.seconds
            for f in item["fields"]:
                store().qa_label(tester_id=t["id"], item_id=item["item_id"], field=f["field"],
                                 verdict=verdicts[f["field"]], comment=comment[:500], auto_verdict=f["auto_verdict"],
                                 seconds_on_item=secs)
            log("qa_review", {"item": item["item_id"], "seconds": secs})
            if len(done_ids) + 1 >= 5:
                store().task(tester_id=t["id"], task="qa_review", success=1, seconds=secs, detail=f"{len(done_ids) + 1} items")
            st.toast(f"Saved. {right_n}/{len(item['fields'])} verdicts match ground truth.")
            st.rerun()

pend = st.session_state.get("qa_pending")
if t is None and pend and pend["item"] == item["item_id"]:
    with st.form("qa_join"):
        st.markdown("**Want this review to count?** Add a name and it is saved with the other reviewers' verdicts, "
                    "so agreement between people can be measured. No email, no real patient data.")
        a, b = st.columns(2)
        nm = a.text_input("Name or handle", max_chars=60)
        role = b.selectbox("Your role", ["Software engineer", "ML / AI engineer", "Data scientist / analyst",
                                         "Healthcare operations / RCM", "Clinician", "Product / design", "Student", "Other"])
        ok = st.checkbox("Store my reviews, page visits and times for this study, reported only in aggregate.")
        if st.form_submit_button("Save my review", type="primary"):
            if not nm.strip() or not ok:
                st.error("Enter a name and tick the box.")
            else:
                tid = store().register(nm, role, "n/a")
                st.session_state.tester = {"id": tid, "name": nm.strip(), "role": role}
                st.session_state.pop("sid", None)
                by = {f["field"]: f for f in item["fields"]}
                for fld, v in pend["verdicts"].items():
                    store().qa_label(tester_id=tid, item_id=pend["item"], field=fld, verdict=v,
                                     comment=pend["comment"][:500], auto_verdict=by[fld]["auto_verdict"], seconds_on_item=0)
                st.session_state.pop("qa_pending", None)
                log("joined", {"role": role, "via": "qa"})
                st.rerun()

all_labels = store().rows(qa_labels)
if all_labels and len({r["tester_id"] for r in all_labels}) >= 2:
    st.markdown("### Reviewer agreement so far")
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
