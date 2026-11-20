import json
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from app.ui import log, setup
from authops.cases.manager import REQUEST_TYPES, CaseManager

setup("Cases and API",
      "When a payor needs the clinician (a peer-to-peer, more records, a corrected signature), an inbox loses the "
      "request and the deadline passes. Here every request becomes a case with a clock, an owner, reminders and "
      "escalation, and a clinic's own systems can drive all of it through the API.")

tab_q, tab_api = st.tabs(["Clinician queue", "External API"])

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
                                   for x in q]), hide_index=True, use_container_width=True)
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
