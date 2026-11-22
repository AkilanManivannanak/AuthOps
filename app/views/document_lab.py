import random
import tempfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw

from app.ui import ASSETS, FOREST, RED, AMBER, Timer, asset_json, log, require_tester, setup, store
from authops.docintel.calibrate import load_scorer
from authops.docintel.evaluate import values_match
from authops.docintel.extract import RuleExtractor, classify_doc
from authops.docintel.ocr import ocr_pages
from authops.ops.userstore import doc_labels
from authops.schemas import DocType
from authops.synth.generate import PAYOR_BY_ID, generate_cases
from authops.synth.render import render_corpus

setup("Document Lab",
      "The AI reads a prior-auth document and fills a structured record. You check it against the page. "
      "Green fields it is sure of, amber it is unsure of, red it refused to guess.")
t = require_tester("so your corrections count")

PAYOR_LABEL = {"NWH": "Northwind (template A, labelled fields)", "KCM": "Keystone (template B, letter prose)",
               "SFB": "Summit (template C, dot leaders, monospace)"}


@st.cache_data(show_spinner=False, max_entries=64)
def make_doc(seed: int, payor: str, outcome: str, condition: str, doc_kind: str):
    case = generate_cases(1, seed=seed, gap_rate=0.0)[0]
    case.payor = PAYOR_BY_ID[payor]
    case.patient.member_id = payor + case.patient.member_id[3:]
    if outcome == "Denied":
        case.injected_gaps = ["missing_signature"]
        case.signature_present, case.signature_date = False, None
    d = Path(tempfile.mkdtemp(prefix="doclab_"))
    manifest = render_corpus([case], d, seed=seed, conditions=(condition,))
    want = "treatment_plan" if doc_kind == "Treatment plan" else None
    doc = next(m for m in manifest if (m["doc_type"] == want) or (want is None and m["doc_type"] != "treatment_plan"))
    return doc


@st.cache_data(show_spinner=False, max_entries=64)
def read_doc(pages: tuple, doc_type: str | None):
    ocr = ocr_pages(list(pages))
    dt = DocType(doc_type) if doc_type else classify_doc(ocr.text)
    ex = RuleExtractor().extract("doc", ocr, dt)
    words = [(w.text, w.conf, w.box, pi) for pi, p in enumerate(ocr.pages) for w in p.words]
    return {"doc_type": dt.value, "fields": {k: v.model_dump() for k, v in ex.fields.items()},
            "ocr_mean": ocr.mean_conf, "words": words, "latency_ms": ex.latency_ms}


src = st.radio("Source", ["Generate a synthetic document", "Upload your own image"], horizontal=True,
               label_visibility="collapsed")
truth, template, pages = None, "tp", []
if src.startswith("Generate"):
    c1, c2, c3, c4, c5 = st.columns([1.2, 1.4, 1, 1, 0.8])
    kind = c1.selectbox("Document", ["Payor determination letter", "Treatment plan"])
    payor = c2.selectbox("Payor and layout", list(PAYOR_LABEL), format_func=PAYOR_LABEL.get)
    outcome = c3.selectbox("Outcome", ["Approved", "Denied"], disabled=kind == "Treatment plan")
    cond = c4.selectbox("Image quality", ["clean", "scan", "fax"], index=2)
    if "doc_seed" not in st.session_state:
        st.session_state.doc_seed = random.randint(1, 10_000)
    if c5.button("New patient", width="stretch"):
        st.session_state.doc_seed = random.randint(1, 10_000)
        Timer("doc").reset()
    doc = make_doc(st.session_state.doc_seed, payor, outcome, cond, kind)
    pages, truth = doc["pages"], doc["truth"]
    template = doc["template"]
    doc_id = f"gen-{doc['doc_id']}-{cond}-{st.session_state.doc_seed}"
    doc_type = doc["doc_type"]
else:
    up = st.file_uploader("PNG or JPG of a synthetic or redacted document. No real patient data.", type=["png", "jpg", "jpeg"])
    if not up:
        st.stop()
    p = Path(tempfile.mkdtemp()) / up.name
    p.write_bytes(up.getvalue())
    pages, doc_type, doc_id = [str(p)], None, f"upload-{up.name}"

with st.spinner("Reading the page..."):
    res = read_doc(tuple(pages), doc_type)
timer = Timer("doc")

left, right = st.columns([1.05, 1])
thr = right.slider("Abstain below this confidence", 0.30, 0.95, 0.55, 0.05,
                   help="Fields below the threshold are left blank and routed to a person instead of guessed.")
scorer = load_scorer(ASSETS / "calibrator.json") if (ASSETS / "calibrator.json").exists() else None

rows, boxes = [], []
for name, fv in res["fields"].items():
    if name == "denial_reason":
        continue
    v, conf = fv["value"], fv["confidence"]
    learned = scorer({"field": name, "conf": conf, "pred": v}, {"template": template, "ocr_mean_conf": res["ocr_mean"]}) \
        if scorer and v not in (None, "", []) else None
    status = "abstained" if (v in (None, "", []) or conf < thr) else ("sure" if conf >= 0.8 else "unsure")
    shown = None if status == "abstained" else v
    rows.append({"Field": name.replace("_", " "), "AI value": "" if shown is None else (", ".join(shown) if isinstance(shown, list) else str(shown)),
                 "Confidence": round(conf, 2), "Learned conf": None if learned is None else round(learned, 2),
                 "Status": status, "Your value": "" if shown is None else (", ".join(shown) if isinstance(shown, list) else str(shown)),
                 "_key": name})
    if v not in (None, "", []):
        sv = str(", ".join(v) if isinstance(v, list) else v)
        toks = {x.strip(",.:").upper() for x in sv.split()}
        if len(sv) == 10 and sv[4] == "-":  # ISO date: also look for the page's own format
            from datetime import date as _d
            dd = _d.fromisoformat(sv)
            toks |= {dd.strftime("%m/%d/%Y"), dd.strftime("%B").upper(), f"{dd.day},", str(dd.year)}
        hits = [w for w in res["words"] if w[0].strip(",.:").upper() in toks and len(w[0]) > 1]
        for w in hits[:6]:
            boxes.append((w[2], w[3], status))

with left:
    show_boxes = st.toggle("Highlight what the AI read", value=True)
    img = Image.open(pages[0]).convert("RGB")
    if show_boxes:
        dr = ImageDraw.Draw(img, "RGBA")
        col = {"sure": (40, 84, 62), "unsure": (201, 139, 30), "abstained": (179, 64, 47)}
        for (x, y, w, h), pi, status in boxes:
            if pi == 0:
                c = col[status]
                dr.rectangle([x - 4, y - 3, x + w + 4, y + h + 3], outline=c + (255,), width=4, fill=c + (45,))
    st.image(img, width="stretch")
    st.caption(f"Read in {res['latency_ms'] / 1000:.1f}s · mean OCR confidence {res['ocr_mean']:.0f} · "
               f"classified as **{res['doc_type'].replace('_', ' ')}**")

with right:
    df = pd.DataFrame(rows)
    colors = {"sure": FOREST, "unsure": AMBER, "abstained": RED}
    k1, k2, k3 = st.columns(3)
    for col, s in zip((k1, k2, k3), ("sure", "unsure", "abstained")):
        col.markdown(f"<div class='ao-tile'><div class='ao-fig' style='color:{colors[s]};font-size:2.2rem'>"
                     f"{(df.Status == s).sum()}</div><div class='ao-lab'>{s}</div></div>", unsafe_allow_html=True)
    edited = st.data_editor(
        df.drop(columns=["_key"]), hide_index=True, width="stretch", key=f"ed_{doc_id}_{thr}",
        disabled=["Field", "AI value", "Confidence", "Learned conf", "Status"],
        column_config={"Field": st.column_config.TextColumn(width="small"),
                       "Confidence": st.column_config.ProgressColumn("Conf", min_value=0, max_value=1, format="%.2f", width="small"),
                       "Learned conf": st.column_config.ProgressColumn("Learned", min_value=0, max_value=1, format="%.2f", width="small"),
                       "Status": st.column_config.TextColumn(width="small"),
                       "Your value": st.column_config.TextColumn("Your value ✎", width="medium",
                                                                 help="Fix anything wrong. Fill blanks if the page has the value.")})
    if st.button("Submit my review", type="primary", width="stretch", disabled=truth is None and not t):
        secs = timer.seconds
        ai_ok = you_ok = n = 0
        result_rows = []
        for (_, r), key in zip(edited.iterrows(), df["_key"]):
            tv = truth.get(key) if truth else None
            ai_val = r["AI value"] or None
            you_val = r["Your value"].strip() or None
            if truth is not None:
                listy = isinstance(tv, list)
                def to_cmp(s):
                    return ([x.strip() for x in s.split(",")] if (s and listy) else s)
                a_ok = values_match(key, to_cmp(ai_val), tv)
                y_ok = values_match(key, to_cmp(you_val), tv)
                ai_ok, you_ok, n = ai_ok + a_ok, you_ok + y_ok, n + 1
                result_rows.append({"Field": r["Field"], "Truth": tv if not isinstance(tv, list) else ", ".join(tv),
                                    "AI": "✓" if a_ok else "✕", "You": "✓" if y_ok else "✕"})
            if t:
                store().doc_label(tester_id=t["id"], doc_id=doc_id, field=key, model_value=str(ai_val),
                                  human_value=str(you_val), truth_value=str(tv), model_conf=float(r["Confidence"]),
                                  seconds_on_doc=secs)
        log("doc_review", {"doc_id": doc_id, "ai_ok": ai_ok, "you_ok": you_ok, "n": n, "seconds": secs})
        if t:
            reviewed = len({r["doc_id"] for r in store().rows(doc_labels)
                            if r["tester_id"] == t["id"]})
            if reviewed >= 3:
                store().task(tester_id=t["id"], task="doc_review", success=1, seconds=secs, detail=f"{reviewed} docs")
        if truth is not None:
            st.markdown(f"**AI {ai_ok}/{n} correct · you {you_ok}/{n} correct** in {secs:.0f}s")
            st.dataframe(pd.DataFrame(result_rows), hide_index=True, width="stretch")
            if you_ok > ai_ok:
                st.success(f"You caught {you_ok - ai_ok} field(s) the AI got wrong or left blank. That is the human-in-the-loop value.")

st.markdown("### Where to set the threshold")
rows_all = asset_json("extraction_rows.json")
rc = asset_json("risk_coverage.json")
if rows_all and rc:
    answered = [r for r in rows_all if r["pred"] not in (None, "", [])]
    cov_now = sum(r["conf"] >= thr for r in answered) / len(rows_all)
    data = pd.DataFrame([dict(x, score="heuristic") for x in rc["heuristic"]] +
                        [dict(x, score="learned calibrator") for x in rc["learned"]])
    base = alt.Chart(data).mark_line(point=True, strokeWidth=3).encode(
        x=alt.X("coverage:Q", title="share of fields filled automatically", axis=alt.Axis(format="%")),
        y=alt.Y("silent_error:Q", title="wrong values that would reach the payor", axis=alt.Axis(format="%")),
        color=alt.Color("score:N", scale=alt.Scale(range=["#9A9A9A", FOREST]), legend=alt.Legend(orient="top")))
    rule = alt.Chart(pd.DataFrame({"c": [cov_now]})).mark_rule(color=RED, strokeDash=[6, 4], size=2).encode(x="c:Q")
    st.altair_chart((base + rule).properties(height=300), width="stretch")
    st.caption(f"Held-out cases. The red line is where your threshold of {thr:.2f} puts the heuristic "
               f"(about {cov_now:.0%} of fields filled). Lower thresholds fill more fields and let more errors through; "
               "on these documents the learned calibrator tracks the heuristic closely and does not beat it yet.")
