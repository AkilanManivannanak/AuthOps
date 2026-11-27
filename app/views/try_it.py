import hashlib
import json
import random
import tempfile
from datetime import date
from pathlib import Path

import streamlit as st

from app.ui import log, setup, switch
from app.widgets.assist_view import assist_view
from authops.assist.reader import _default_steps, check_plan, ocr_text, on_disk, png_pages, read_letter
from authops.llm import llm_available

from app.account import role, save, today, ws  # noqa: E402

R = role()
setup("Read a letter" if R == "patient" else "Check a document",
      "Take a photo of an insurance letter and get the decision, the dates and what to do next." if R == "patient" else
      "Upload a treatment plan before it goes out, or a payor's letter when it comes back.")

AI_DAILY = 6   # AI reads per person per day, counted on the server, to keep the free demo affordable
MODES = ({"My insurance letter": "letter"} if R == "patient" else
         {"Before we send a prior auth": "plan", "A payor's letter came back": "letter", "Show me what was read": "raw"})
mode = MODES[switch(MODES, "mode")] if len(MODES) > 1 else "letter"

st.markdown("<div class='ao-muted' style='margin:-.2rem 0 .8rem'>🔒 Cover names and member IDs before you upload. "
            "Your account keeps the result (decision, dates and checks), never the image or the letter's wording; "
            "the page is deleted as soon as it has been read. The AI reader sends the page to a secure AI service to be read.</div>",
            unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def _sample(kind: str, n: int = 0) -> list[bytes]:
    """Three different samples per kind, so each person can rate several answers:
    member notice approved / partial / denied; clinic letters from three cases; plans unsigned / signed / expired."""
    from datetime import timedelta

    from authops.synth.generate import PAYOR_BY_ID, generate_cases
    from authops.synth.render import render_letter, render_member_letter, render_treatment_plan, save_doc
    c = generate_cases(1, seed=[7, 8, 9][n % 3], gap_rate=0.0)[0]
    rng = random.Random(3 + n)
    with tempfile.TemporaryDirectory(prefix="sample_") as d:
        if kind == "member_letter":
            c.payor = PAYOR_BY_ID["KCM"]
            w = render_member_letter(c, rng, decision=["partial", "denied", "approved"][n % 3])
            paths = save_doc(w, Path(d), "letter", "scan", rng)
        elif kind == "letter":
            c.payor = PAYOR_BY_ID["KCM"]
            w, _, _ = render_letter(c, rng)
            paths = save_doc(w, Path(d), "letter", "scan", rng)
        else:
            if n % 3 == 0:
                c.signature_present, c.signature_date = False, None
            elif n % 3 == 2:
                c.start_date, c.end_date = c.start_date - timedelta(days=400), c.end_date - timedelta(days=400)
            paths = save_doc(render_treatment_plan(c, rng, False), Path(d), "plan", "scan", rng)
        return [Path(p).read_bytes() for p in paths]


def _doc(pngs: list[bytes], sample: bool) -> dict:
    """A document is known by a hash of its pages, so a result always belongs to the image beside it."""
    return {"png": pngs, "id": hashlib.sha256(b"".join(pngs)).hexdigest()[:16], "sample": sample, "mode": mode}


def _who() -> str:
    """Who the daily AI quota is counted for: the account, or for guests the network address (hashed), so a
    reload or a new tab does not reset it."""
    from app.ui import session_id, who_am_i
    w, _ = who_am_i()
    if w:
        return w
    ip = getattr(st.context, "ip_address", None)
    return ("ip:" + hashlib.sha256(ip.encode()).hexdigest()[:16]) if ip else ("session:" + session_id())


a, b, c = st.columns([2.2, 1, 1])
up = a.file_uploader("Photo, scan or PDF", type=["png", "jpg", "jpeg", "pdf"], label_visibility="collapsed")
seen = st.session_state.setdefault("samples_seen", {})
sample = b.button(("Try another sample" if seen.get(mode) else "Use a sample ") +
                  ("" if seen.get(mode) else ("letter" if mode == "letter" else "plan")), width="stretch")
from app.ui import store  # noqa: E402

used = store().ai_calls(_who(), f"{date.today():%Y-%m-%d}")
left_today = max(0, AI_DAILY - used)
ai_on = c.toggle("AI reader", value=llm_available() and left_today > 0, disabled=not llm_available() or left_today == 0,
                 help="The AI reads the page images and answers in a fixed shape. An answer only counts when the line "
                      "it came from is found on the page. Off: OCR and rule checks only.")
if not llm_available():
    c.caption("Rule checks on this deployment")
elif left_today == 0:
    c.caption("Today's AI reads are used up; rule checks still work")

if sample:
    kind = ("member_letter" if R == "patient" else "letter") if mode == "letter" else "plan"
    n = seen.get(mode, 0)
    seen[mode] = n + 1
    st.session_state.doc = _doc(_sample(kind, n), True)
elif up is not None and st.session_state.get("_up") != up.name + str(up.size):
    st.session_state._up = up.name + str(up.size)
    st.session_state.doc = _doc(png_pages(up.getvalue(), up.name), False)
if st.session_state.get("doc") and st.session_state.doc.get("mode") != mode and mode != "raw":
    st.session_state.pop("doc")   # a new mode needs its own document: never check a letter as a plan

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
        doc = st.session_state.get("doc") or {}
        try:
            store().feedback(session_id(), who, role, mode, "right" if v == "Yes" else "wrong", what=what,
                             layer="ai" if res.get("layer") == "AI" else "rules", comment=note,
                             doc_id=doc.get("id", ""), is_sample=doc.get("sample", False),
                             result=json.dumps(_snapshot(res), default=str))
        except Exception as e:
            log("feedback_error", {"err": type(e).__name__})
            st.warning("That didn't save. Please try again in a moment.")
            return
        log("feedback", {"mode": mode, "verdict": v})
        done.add(k)
        st.rerun()


def _snapshot(res: dict) -> dict:
    """What was shown, without free text that could carry a name: the fields and check results only."""
    keep = ("kind", "layer", "decision", "approved_amount", "start", "end", "appeal_days", "deadline", "score",
            "to_fix", "unverified")
    return {**{k: res.get(k) for k in keep if k in res},
            "checks": [{"name": c["name"], "status": c["status"], "layer": c.get("layer")} for c in res.get("checks", [])]}


doc = st.session_state.get("doc")
if not doc:
    st.markdown("""<div class='ao-card' style='text-align:center;padding:48px 20px;margin-top:10px'>
    <div style='font-family:Fraunces,Georgia,serif;font-size:1.6rem'>Drop a letter or a plan above</div>
    <div class='ao-muted'>or press "Use a sample" to see it work on a sample one</div></div>""", unsafe_allow_html=True)
    st.stop()

key = (doc["id"], mode, ai_on)
cache = st.session_state.setdefault("assist_cache", {})
if key not in cache:
    llm = None
    if ai_on and store().ai_calls(_who(), f"{date.today():%Y-%m-%d}") < AI_DAILY:   # checked again on the server
        from authops.llm import ClaudeLLM
        llm = ClaudeLLM()
        store().ai_calls(_who(), f"{date.today():%Y-%m-%d}", add=1)
    with st.spinner("Reading the page"), on_disk(doc["png"]) as pages:   # files exist only while being read
        text = ocr_text(pages)
        if mode == "letter":
            cache[key] = read_letter(pages, llm, text=text)
        elif mode == "plan":
            cache[key] = check_plan(pages, llm, text=text, today=date.today())
        else:
            cache[key] = {"text": text, "letter": read_letter(pages, None, text=text)["facts"]}
    log("assist", {"mode": mode, "ai": llm is not None, "sample": doc.get("sample", False)})
    r0, w = cache[key], ws()
    if mode == "letter":   # saved without the letter's own wording: no names leave the page
        w["letters"].insert(0, {"read_on": f"{today():%b %d}", "decision": r0.get("decision"),
                                "deadline": r0.get("deadline"), "start": r0.get("start"), "end": r0.get("end"),
                                "steps": _default_steps(r0.get("decision"))})
        del w["letters"][12:]
        from authops import workspace as W
        W.activity(w, f"Read a payor letter: {r0.get('decision') or 'decision unclear'}", "try_it")
        save("Saved to " + ("My care." if R == "patient" else "your activity."))
    elif mode == "plan":
        w["plans"].insert(0, {"read_on": f"{today():%b %d}", "score": r0.get("score"), "to_fix": r0.get("to_fix")})
        del w["plans"][12:]
        from authops import workspace as W
        what = {"referral": "a referral", "visit_log": "a visit log"}.get(r0.get("kind"), "a treatment plan")
        W.activity(w, f"Checked {what}: {r0.get('to_fix', 0)} to fix", "try_it")
        save()
res = cache[key]

left, right = st.columns([1, 2.2])
left.image(doc["png"][0], width="stretch")
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
