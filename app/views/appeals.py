import pandas as pd
import streamlit as st

from app.ui import log, pill, setup

setup("Appeal a denial", "Triage a denial, then draft the appeal only from quotes in the chart.")
import json as _json  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

from authops.appeals.packet import build_packet, make_denials, verify_letter  # noqa: E402
from authops.docagent.longdoc import make_corpus  # noqa: E402


@st.cache_resource(show_spinner=False)
def _appeal_set():
    cs = make_corpus()
    return {c.chart_id: c for c in cs}, make_denials(cs)

charts, denials = _appeal_set()
st.caption("Each denial is triaged before anyone writes: appeal when the chart already meets the requirement, "
           "corrective resubmission when it does not, specialist review when the evidence is unclear. Appeal "
           "letters are drafted only from verbatim chart quotes, and every citation is re-checked.")
pick = st.selectbox("Denial", range(len(denials)), format_func=lambda i: f"{denials[i].denial_id} · "
                    f"{charts[denials[i].chart_id].specialty.replace('_', ' ')} · "
                    f"{charts[denials[i].chart_id].n_pages}-page chart · {denials[i].reason[:70]}")
d = denials[pick]
chart = charts[d.chart_id]
pk = build_packet(chart, d)
log("appeal_view", {"denial": d.denial_id, "action": pk.action})
from app.widgets.evidence import evidence_view  # noqa: E402
from authops.docagent.validators import _found  # noqa: E402

hits = [{"pages": list(f.pages), "quote": f.quote[:400],
         "ok": bool(f.pages) and any(_found(f.quote[:120], chart.pages[p - 1]) for p in f.pages if 1 <= p <= chart.n_pages)}
        for f in pk.evidence]
why = {"appeal": "The chart already meets the requirement the payor says is missing, so this is an appeal.",
       "corrective_resubmission": "The chart does not meet the requirement, so fixing and resubmitting beats appealing.",
       "specialist_review": "The evidence is unclear, so a specialist decides before anything is sent."}[pk.action]
evidence_view(pk.action, d.reason, why, chart.pages, hits, key=f"ev_{d.denial_id}")
with st.expander("Denial letter"):
    st.code(d.letter, language=None)
if pk.action == "appeal":
    draft = st.text_area("Draft appeal (edit before signing)", pk.letter, height=320, key=f"appeal_{d.denial_id}")
    ok = verify_letter(chart, draft)
    st.markdown(pill("All citations verified against the chart", "ok") if ok else
                pill("A quoted passage no longer matches its cited page", "bad"), unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    b1.download_button("Download appeal (.txt)", draft, f"{d.denial_id}_appeal.txt", disabled=not ok)
    if b2.button("Send to the clinician for signature", disabled=not ok):
        cm = st.session_state.get("cm")
        if cm:
            c = cm.open(d.denial_id, "appeal", chart.specialty, d.chart_id, st.session_state.now)
            st.success(f"Opened {c.case_id} in the clinician queue (due in 30 days).")
            log("appeal_case", {"denial": d.denial_id})
else:
    st.info(pk.fix or pk.note)
with st.expander("Backtest"):
    rep = _Path(__file__).resolve().parents[2] / "reports" / "intel.json"
    if rep.exists():
        ap = _json.loads(rep.read_text()).get("appeals", {})
        st.dataframe(pd.DataFrame([{k: v for k, v in a.items() if k != "rows"} for a in ap.values()]),
                     hide_index=True, width="stretch")
    st.caption("30 denials on 12-150 page charts, 18 wrongful and 12 correct. The offline finder is "
               "template-aware, so its result only shows the pipeline works; the Claude document agent is "
               "the real test of finding the evidence.")

