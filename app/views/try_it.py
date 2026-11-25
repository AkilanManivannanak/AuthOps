import json
import random
import tempfile
from datetime import date
from pathlib import Path

import streamlit as st

from app.ui import log, setup, switch
from app.widgets.assist_view import assist_view
from authops.assist.reader import check_plan, ocr_text, read_letter, to_pages
from authops.llm import llm_available

from app.account import role, save, today, ws  # noqa: E402

R = role()
setup("Read a letter" if R == "patient" else "Check a document",
      "Take a photo of an insurance letter and get the decision, the dates and what to do next." if R == "patient" else
      "Upload a treatment plan before it goes out, or a payor's letter when it comes back.")

AI_CAP = 6   # AI reads per visit, to keep the free demo affordable
MODES = ({"My insurance letter": "letter"} if R == "patient" else
         {"Before we send a prior auth": "plan", "A payor's letter came back": "letter", "Show me what was read": "raw"})
mode = MODES[switch(MODES, "mode")] if len(MODES) > 1 else "letter"

st.markdown("<div class='ao-muted' style='margin:-.2rem 0 .8rem'>🔒 Cover names and member IDs before you upload. "
            "Only the result is kept in your account, never the image. The AI reader sends the page to a secure AI service to be read.</div>",
            unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def _sample(kind: str) -> list[str]:
    from authops.synth.generate import PAYOR_BY_ID, generate_cases
    from authops.synth.render import render_letter, render_treatment_plan, save_doc
    c = generate_cases(1, seed=7, gap_rate=0.0)[0]
    rng, d = random.Random(3), Path(tempfile.mkdtemp(prefix="sample_"))
    if kind == "letter":
        c.payor = PAYOR_BY_ID["KCM"]
        w, _, _ = render_letter(c, rng)
        return save_doc(w, d, "letter", "scan", rng)
    c.signature_present, c.signature_date = False, None
    return save_doc(render_treatment_plan(c, rng, False), d, "plan", "scan", rng)


a, b, c = st.columns([2.2, 1, 1])
up = a.file_uploader("Photo, scan or PDF", type=["png", "jpg", "jpeg", "pdf"], label_visibility="collapsed")
sample = b.button("Use a sample " + ("letter" if mode == "letter" else "plan"), width="stretch")
used = st.session_state.setdefault("ai_used", 0)
ai_on = c.toggle("AI reader", value=llm_available() and used < AI_CAP, disabled=not llm_available() or used >= AI_CAP,
                 help="the AI reads the page images and answers in a fixed shape; every quote is checked against the "
                      "page. Off: OCR and rule checks only.")
if not llm_available():
    c.caption("Rules only on this deployment")

if sample:
    st.session_state.doc = {"pages": _sample("letter" if mode == "letter" else "plan"), "name": "sample"}
elif up is not None and st.session_state.get("doc", {}).get("name") != up.name + str(up.size):
    st.session_state.doc = {"pages": [str(p) for p in to_pages(up.getvalue(), up.name)], "name": up.name + str(up.size)}

PARTS = {"letter": ["the decision", "the deadline", "the dates", "the amount approved", "the next steps", "something else"],
         "plan": ["a missing item it flagged", "something it missed", "the codes", "the dates", "something else"]}


def _feedback(mode: str, res: dict, key) -> None:
    """Was this right? Stored with the layer that answered, read by the AI Ops desk usage reports."""
    done = st.session_state.setdefault("fb_done", set())
    k = f"{mode}|{abs(hash(key))}"
    if k in done:
        st.caption("Thanks. Your answer goes into the error review on the AI Ops desk.")
        return
    st.markdown("<div class='ao-eyebrow' style='margin-top:.6rem'>Was this right?</div>", unsafe_allow_html=True)
    v = st.segmented_control("Was this right?", ["Yes", "Not quite"], key=f"fbv_{k}", label_visibility="collapsed")
    if not v:
        return
    what, note = "", ""
    if v == "Not quite":
        what = st.selectbox("What was off?", PARTS[mode], key=f"fbw_{k}")
        note = st.text_input("What should it have said? (optional)", key=f"fbn_{k}")
    if st.button("Send", key=f"fbs_{k}"):
        from app.ui import store, who_am_i, session_id
        who, role = who_am_i()
        try:
            store().feedback(session_id(), who, role, mode, "right" if v == "Yes" else "wrong", what=what,
                             layer="ai" if res.get("layer") == "AI" else "rules", comment=note)
        except Exception:
            pass
        log("feedback", {"mode": mode, "verdict": v})
        done.add(k)
        st.rerun()


doc = st.session_state.get("doc")
if not doc:
    st.markdown("""<div class='ao-card' style='text-align:center;padding:48px 20px;margin-top:10px'>
    <div style='font-family:Fraunces,Georgia,serif;font-size:1.6rem'>Drop a letter or a plan above</div>
    <div class='ao-muted'>or press "Use a sample" to see it work on a sample one</div></div>""", unsafe_allow_html=True)
    st.stop()

pages = [Path(p) for p in doc["pages"]]
key = (doc["name"], mode, ai_on)
cache = st.session_state.setdefault("assist_cache", {})
if key not in cache:
    llm = None
    if ai_on:
        from authops.llm import ClaudeLLM
        llm = ClaudeLLM()
        st.session_state.ai_used += 1
    with st.spinner("Reading the page"):
        text = ocr_text(pages)
        if mode == "letter":
            cache[key] = read_letter(pages, llm, text=text)
        elif mode == "plan":
            cache[key] = check_plan(pages, llm, text=text, today=date.today())
        else:
            cache[key] = {"text": text, "letter": read_letter(pages, None, text=text)["facts"]}
    log("assist", {"mode": mode, "ai": ai_on, "sample": doc["name"] == "sample"})
    r0, w = cache[key], ws()
    if mode == "letter":
        w["letters"].insert(0, {"read_on": f"{today():%b %d}", "decision": r0.get("decision"), "summary": r0.get("summary"),
                                "deadline": r0.get("deadline"), "start": r0.get("start"), "end": r0.get("end"),
                                "service": r0.get("service"), "steps": r0.get("next_steps", [])})
        del w["letters"][12:]
        from authops import workspace as W
        W.activity(w, f"Read a payor letter: {r0.get('decision') or 'decision unclear'}", "try_it")
        save("Saved to " + ("My care." if R == "patient" else "your activity."))
    elif mode == "plan":
        w["plans"].insert(0, {"read_on": f"{today():%b %d}", "score": r0.get("score"), "to_fix": r0.get("to_fix"),
                              "summary": r0.get("summary")})
        del w["plans"][12:]
        from authops import workspace as W
        W.activity(w, f"Checked a treatment plan: {r0.get('to_fix', 0)} to fix", "try_it")
        save()
res = cache[key]

left, right = st.columns([1, 2.2])
left.image(str(pages[0]), width="stretch")
with right:
    if mode in ("letter", "plan"):
        assist_view(mode, res, key=f"av_{abs(hash(key))}")
        _feedback(mode, res, key)
    else:
        f = res["letter"]
        st.markdown("#### What the reader pulled off the page")
        rows = {"Decision words": f["decision"] or "none", "Amount": f["units"] or "none",
                "Diagnosis codes": ", ".join(f["icd10"]) or "none", "Service codes": ", ".join(f["cpt"]) or "none",
                "NPIs": ", ".join(f"{n['npi']} ({'valid' if n['valid'] else 'fails checksum'})" for n in f["npis"]) or "none",
                "Dates": ", ".join(d.isoformat() for d in f["dates"]) or "none",
                "Appeal window": f"{f['appeal_days']} days" if f["appeal_days"] else "not stated"}
        for k_, v in rows.items():
            st.markdown(f"**{k_}** &nbsp; {v}")
        with st.expander("Full OCR text"):
            st.text(res["text"])
        st.download_button("Download as JSON", json.dumps({k_: str(v) for k_, v in rows.items()}, indent=1),
                           "authops_read.json")

st.markdown("<div style='height:.8rem'></div><div class='ao-eyebrow'>What next</div>", unsafe_allow_html=True)
n1, n2, _ = st.columns([1, 1, 2])
if R == "patient":
    n1.page_link("app/views/care_readiness.py", label="See it in My care", icon=":material/arrow_forward:")
    n2.page_link("app/views/benefit_checks.py", label="Estimate what visits will cost", icon=":material/arrow_forward:",
                 query_params={"bc": "Cost calculator"})
else:
    n1.page_link("app/views/care_readiness.py", label="Back to today's patients", icon=":material/arrow_forward:")
    n2.page_link("app/views/prior_authorizations.py", label="Work the next request", icon=":material/arrow_forward:")
