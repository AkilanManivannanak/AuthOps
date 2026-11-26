import json

import streamlit as st

from app.ui import FOREST, RED, log, pill, setup
from authops.channels.router import build_pas_bundle, choose_channel
from authops.synth.generate import PAYOR_BY_ID, PAYORS, generate_cases
from authops.validation.rules import load_requirements

setup("FHIR and channels", "Every request goes to the best channel the payor offers: FHIR API, portal or phone.")
req = load_requirements()

steps = [("Jan 17, 2024", "CMS-0057-F finalized"), ("Jan 1, 2026", "72h urgent / 7-day standard decisions; public PA metrics"),
         ("Jan 1, 2027", "Prior Authorization, Patient Access, Provider Access, Payer-to-Payer FHIR APIs live")]
cells = "".join(f"<div class='s' style='animation-delay:{i * 0.25}s'><div class='d'>{d}</div><div>{t}</div></div>"
                for i, (d, t) in enumerate(steps))
st.iframe(f"""<style>body{{margin:0;font-family:Inter,system-ui,sans-serif}} .r{{display:flex;gap:12px}}
.s{{flex:1;border-top:4px solid {FOREST};background:#fff;border-radius:12px;padding:12px;opacity:0;animation:in .5s forwards;font-size:.9rem}}
.d{{font-family:Fraunces,Georgia,serif;font-size:1.4rem;font-weight:300}} @keyframes in{{to{{opacity:1}}}}</style><div class="r">{cells}</div>""",
                height=130)

pid = st.selectbox("Payor", [p.payor_id for p in PAYORS], format_func=lambda x: f"{PAYOR_BY_ID[x].name} "
                   f"({req['payors'][x]['channel']})")
case = generate_cases(1, seed=7)[0].model_dump(mode="json")
case["payor"] = PAYOR_BY_ID[pid].model_dump()
case["patient"]["member_id"] = pid + case["patient"]["member_id"][3:]
ch = choose_channel(case, req)
log("route", {"payor": pid, "channel": ch})

order = ["fhir", "portal", "phone"]
names = {"fhir": "FHIR PA API", "portal": "Browser agent on portal", "phone": "Phone agent"}
chips = " → ".join((pill(names[c], "ok") if c == ch else f"<span class='ao-muted'>{names[c]}</span>") for c in order)
st.markdown(f"**Route:** {chips}", unsafe_allow_html=True)
if ch == "fhir":
    st.markdown("This payor exposes a Prior Authorization API, so no browser is needed. The request goes as a "
                "FHIR R4 Bundle in the Da Vinci PAS shape (valid against base R4; not checked against the PAS profiles):")
    st.json(build_pas_bundle(case), expanded=2)
    if st.button("Submit to the test FHIR endpoint", type="primary"):
        try:
            from app.sandbox import portal_server, sandbox
            from authops.channels.router import submit_fhir

            srv, _ = portal_server()
            r = submit_fhir(srv.url, sandbox()["cases"][0])  # a member the sandbox payor knows
            st.markdown(pill(r["status"], "ok" if r["status"] == "submitted" else "bad") +
                        f" &nbsp; preAuthRef **{r['ref']}** in {r['duration_s']}s (HTTP {r['http']})", unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Test unavailable: {e}")
elif ch == "portal":
    st.markdown("No API yet, so the browser agent submits through the portal. See **Watch the browser agent**.")
else:
    st.markdown("No portal and no API: benefits and status are checked by phone. See **Benefit checks**.")
st.markdown(f"<p class='ao-muted'>The bundle and the 278 cover a working subset of each implementation guide, not a certified implementation. "
            f"<span style='color:{RED}'>Drugs are out of scope</span> of the CMS-0057-F PA API.</p>", unsafe_allow_html=True)
st.markdown("#### The same request as an X12 278")
st.caption("Clearinghouses and many payors still exchange prior authorizations as HIPAA X12 278 files "
           "(005010X217). The request is built, checked the way a clearinghouse checks it, and answered by the test payor.")
from authops.channels.x12 import build_278_request, build_278_response, parse_278_response, validate_x12  # noqa: E402

from datetime import datetime  # noqa: E402
import hashlib  # noqa: E402

FIXED = datetime(2026, 11, 25, 9, 0)   # a fixed clock so the file and its auth number are the same on every run
x = build_278_request(case, ctrl=101, now=FIXED)
errs = validate_x12(x)
c1, c2 = st.columns(2)
with c1:
    st.markdown(pill("Envelope valid", "ok") if not errs else pill(f"{len(errs)} envelope errors", "bad"),
                unsafe_allow_html=True)
    st.code(x.replace("~", "~\n"), language=None)
with c2:
    dec = st.radio("Test payor answers", ["approved", "partial", "denied", "pended"], horizontal=True, key="x12_dec")
    units = int(case["requested_units"])
    resp = build_278_response(x, dec, units if dec == "approved" else max(1, units * 2 // 3) if dec == "partial" else None,
                              auth="" if dec in ("denied", "pended") else f"{pid}-{int(hashlib.sha256(case['case_id'].encode()).hexdigest()[:7], 16) % 10**7:07d}",
                              reason={"denied": "NME", "pended": "AN"}.get(dec, ""), now=FIXED)
    r = parse_278_response(resp)
    st.markdown(f"**Read back:** {r['decision']} (HCR {r['action_code']})"
                + (f" · authorization **{r['auth_number']}**" if r["auth_number"] else "")
                + (f" · **{r['approved_quantity']}** approved" if r["approved_quantity"] else "")
                + (f" · {r['start']} to {r['end']}" if r["start"] else "")
                + (f" · reason code {r['reason_code']}" if r["reason_code"] else ""))
    st.code(resp.replace("~", "~\n"), language=None)
    log("x12", {"payor": pid, "decision": dec})

with st.expander("Raw case"):
    st.code(json.dumps(case, indent=1)[:3000], language="json")
