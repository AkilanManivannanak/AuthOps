import json
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from app.ui import log, pill, setup
from authops.cases.manager import REQUEST_TYPES, CaseManager

setup("Cases and API", "Payor requests become cases with deadlines. Denials become appeals or fixes.")

tab_q, tab_appeal, tab_api = st.tabs(["Clinician queue", "Appeals", "External API"])

with tab_q:
    if "cm" not in st.session_state or st.button("Reset demo"):
        cm = CaseManager()
        t0 = datetime(2026, 11, 2, 9, 0)
        for i, (rt, sp) in enumerate([("peer_to_peer", "aba"), ("additional_info", "physical_therapy"),
                                      ("medical_records", "aba"), ("signature_correction", "behavioral_health"),
                                      ("peer_to_peer", "physical_therapy")]):
            cm.open(f"AU-{1000 + i}", rt, sp, f"Patient {chr(65 + i)}", t0 + timedelta(hours=i * 3))
        st.session_state.cm, st.session_state.now = cm, t0 + timedelta(hours=12)
    cm, now = st.session_state.cm, st.session_state.now
    a, b, c = st.columns([1, 1, 2])
    if a.button("Advance 12 hours"):
        st.session_state.now = now = now + timedelta(hours=12)
    if b.button("Advance 2 days"):
        st.session_state.now = now = now + timedelta(days=2)
    acts = cm.tick(now)
    c.markdown(f"**Clock:** {now:%a %b %d, %H:%M}")
    for x in acts:
        st.toast(f"{x['case_id']}: {x['action']}" + (f" → {x['to']}" if x.get("to") else ""))
    q = cm.queue(now)
    if q:
        st.dataframe(pd.DataFrame([{"case": x["case_id"], "type": x["request_type"].replace("_", " "),
                                    "owner": x["assignee"], "hours left": x["hours_left"],
                                    "SLA used": f"{x['sla_used']:.0%}", "reminders": ", ".join(x["reminders_sent"]),
                                    "escalated": "yes" if x["escalated"] else "", "what to do": x["action"]}
                                   for x in q]), hide_index=True, width="stretch")
        pick = st.selectbox("Respond to", [x["case_id"] for x in q])
        resp = st.text_input("Response", "Peer-to-peer completed with the medical director; notes uploaded.")
        if st.button("Send response"):
            cm.respond(pick, resp, now)
            log("case_respond", {"case": pick})
            st.rerun()
    else:
        st.success("Queue is empty.")
    s = cm.stats()
    st.markdown(f"**{s['cases']} cases** · {s['open']} open · {s['responded_in_sla']} answered in time · "
                f"{s['expired']} expired · {s['escalated']} escalated")
    with st.expander("Audit trail"):
        for cid, cc in cm.cases.items():
            st.markdown(f"**{cid}** ({cc.request_type.replace('_', ' ')})")
            st.code("\n".join(f"{w}  {t:24s} {n}" for w, t, n in cc.history), language=None)
    st.caption("Deadlines per request type: " + "; ".join(f"{k.replace('_', ' ')} {v[0]} h" for k, v in REQUEST_TYPES.items())
               + ". The real deadlines vary by payor; these are illustrative.")

with tab_appeal:
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
    left, right = st.columns([1, 1.25])
    left.markdown("**Denial letter**")
    left.code(d.letter, language=None)
    label = {"appeal": ("Appeal: the chart meets the requirement", "ok"),
             "corrective_resubmission": ("Corrective resubmission: the chart does not meet it", "bad"),
             "specialist_review": ("Specialist review: evidence unclear", "warn")}[pk.action]
    right.markdown(f"**Triage** &nbsp; <span class='ao-pill ao-{label[1]}'>{label[0]}</span>", unsafe_allow_html=True)
    for f in pk.evidence:
        right.markdown(f"Evidence on chart page{'s' if len(f.pages) > 1 else ''} "
                       f"{', '.join(map(str, f.pages))}: _{f.quote[:240]}_")
        with right.expander("Show the cited page"):
            st.code(chart.pages[f.pages[0] - 1] if f.pages else "(none)", language=None)
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

with tab_api:
    st.markdown("Calls below run against the real API code in this process (FastAPI test client). Header "
                "`X-API-Key: demo-key`.")
    from fastapi.testclient import TestClient

    from authops.api.app import create_app, verify_signature
    from authops.synth.generate import luhn_npi

    if "api" not in st.session_state:
        app = create_app(today=date(2026, 11, 2))
        st.session_state.api = (app, TestClient(app))
        st.session_state.hook = st.session_state.api[1].post(
            "/v1/webhooks", json={"url": "https://clinic.example/hooks"}, headers={"X-API-Key": "demo-key"}).json()
    app, client = st.session_state.api
    H = {"X-API-Key": "demo-key"}
    body = {"patient_first": "Ava", "patient_last": "Sample", "dob": "2017-03-02", "member_id": "NWH12345678",
            "payor_id": "NWH", "specialty": "aba", "icd10_codes": ["F84.0"], "cpt_codes": ["97153"], "units": 120,
            "start_date": "2026-11-10", "end_date": "2027-05-10", "provider_name": "Dana Whitfield",
            "provider_npi": luhn_npi("123456789"), "signature_date": "2026-10-30"}
    edited = st.text_area("POST /v1/authorizations", json.dumps(body, indent=2), height=300)
    c1, c2 = st.columns(2)
    if c1.button("Send request"):
        try:
            r = client.post("/v1/authorizations", json=json.loads(edited), headers=H)
            st.session_state.last_auth = r.json()
            log("api_create", {"status": r.status_code})
        except json.JSONDecodeError:
            st.error("That is not valid JSON.")
    if st.session_state.get("last_auth"):
        st.json(st.session_state.last_auth)
        aid = st.session_state.last_auth.get("id")
        ev = c2.selectbox("Simulate a payor event", ["peer_to_peer", "additional_info", "approved", "denied"])
        if aid and c2.button("POST /events"):
            st.json(client.post(f"/v1/authorizations/{aid}/events", json={"type": ev, "units_approved": 120}, headers=H).json())
    d = app.state.deliveries
    st.markdown(f"**Webhook deliveries:** {len(d)}")
    if d:
        last = d[-1]
        ok = verify_signature(st.session_state.hook["secret"], last["body"], last["signature"])
        st.code(f"X-AuthOps-Event: {last['event']}\nX-AuthOps-Signature: {last['signature']}\n"
                f"verified with the subscriber's secret: {ok}\n\n{last['body'][:600]}", language=None)
    st.caption("Run it as a real server: `uvicorn authops.api.app:app --port 8100`, then open /docs for the OpenAPI page.")
