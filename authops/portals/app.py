"""Mock payor portals (sandbox) plus a mock FHIR Prior Authorization API.

Portals have no staging environments, so Silna backtests agents in sandboxes before
real submissions. These three fictional portals reproduce the failure modes their AI
Operations team wrote about, at increasing difficulty:

northwind  commercial. Plain forms, native date inputs, a marketing survey modal that
           blocks clicks on a share of page loads.
keystone   Medicaid MCO. Form lives inside an iframe, member ID needs a masked format,
           a custom calendar widget instead of date inputs, a session notice that pops
           up after a delay, conditional ABA fields (school schedule).
lakeshore  regional commercial plan, held out: no hand-written playbook. Different labels for
           every field, a patient lookup step before the form, date of birth typed as MM/DD/YYYY
           text, a decoy "Save draft" button, and a required attestation checkbox. Used to test
           automatic configuration on a portal nobody configured by hand.
summit     federal. TOTP MFA, one live session per credential (a second login kicks
           the first), lockout after 3 bad passwords, a flaky 503 on submit, a
           multi-step wizard, per-file document type and PDF-only uploads.

The FHIR endpoint takes a Da Vinci PAS style Bundle (Claim with use=preauthorization)
and answers with a ClaimResponse: the CMS-0057-F direction where portals stop being
the only channel.
"""
from __future__ import annotations

import html
import json
import random
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pyotp
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

# ----------------------------------------------------------------- state

CREDENTIALS = {
    "northwind": [{"username": "nw_ops_1", "password": "Nw!pass-1"},
                  {"username": "nw_ops_2", "password": "Nw!pass-2"}],
    "keystone": [{"username": "ks.agent1", "password": "Ks#2026a"},
                 {"username": "ks.agent2", "password": "Ks#2026b"}],
    "summit": [{"username": "sfb-ops-a", "password": "Sfb$alpha9", "totp": "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"},
               {"username": "sfb-ops-b", "password": "Sfb$bravo9", "totp": "KRSXG5CTMVRXEZLUKRSXG5CTMVRXEZLU"},
               # stale credential: password rotated by the payor, agent must classify and disable
               {"username": "sfb-ops-c", "password": "Sfb$charlie9-OLD", "totp": "MFRGGZDFMZTWQ2LKMFRGGZDFMZTWQ2LK"}],
}
CREDENTIALS["lakeshore"] = [{"username": "LSP-40117", "password": "Lake!shore7"},
                             {"username": "LSP-40118", "password": "Lake!shore8"}]
SUMMIT_REAL_PASSWORDS = {"sfb-ops-a": "Sfb$alpha9", "sfb-ops-b": "Sfb$bravo9", "sfb-ops-c": "Sfb$charlie9-NEW"}


@dataclass
class Chaos:
    survey_modal_rate: float = 0.35
    session_notice_delay_ms: int = 900
    summit_503_rate: float = 0.15
    summit_kick_rate: float = 0.08  # a human signs in with the same credential mid-run
    seed: int = 3
    # northwind release: "" (current), "v2" (relabeled and reordered form, new button, optional
    # place of service) or "v2-required" (v2, and place of service becomes required)
    northwind_release: str = ""


@dataclass
class PortalState:
    members: dict = field(default_factory=dict)  # member_id -> case dict (eligibility DB)
    sessions: dict = field(default_factory=dict)  # token -> (portal, username)
    summit_live: dict = field(default_factory=dict)  # username -> token (single session)
    summit_pending_mfa: dict = field(default_factory=dict)
    summit_fail: dict = field(default_factory=dict)
    summit_locked: set = field(default_factory=set)
    wizard: dict = field(default_factory=dict)  # token -> partial summit request
    lookup: dict = field(default_factory=dict)  # lakeshore token -> case found at patient lookup
    submissions: list = field(default_factory=list)
    events: list = field(default_factory=list)


def create_app(cases_path: str | Path | None = None, chaos: Chaos | None = None) -> FastAPI:
    app = FastAPI(title="AuthOps mock payor portals")
    st = PortalState()
    chaos = chaos or Chaos()
    rng = random.Random(chaos.seed)
    if cases_path:
        for c in json.loads(Path(cases_path).read_text()):
            st.members[c["patient"]["member_id"]] = c
    app.state.portal = st

    def page(title: str, body: str, portal: str = "") -> HTMLResponse:
        css = """body{font-family:Arial,sans-serif;margin:0;background:#f4f6f8}
        header{background:#1d3557;color:#fff;padding:14px 24px;font-size:20px}
        main{padding:24px;max-width:860px} label{display:block;margin-top:12px;font-weight:600}
        input,select{padding:6px;margin-top:4px;min-width:280px} button{margin-top:16px;padding:8px 18px}
        .err{color:#b00020;font-weight:600}.modal{position:fixed;inset:0;background:rgba(0,0,0,.55);
        display:flex;align-items:center;justify-content:center;z-index:1000}
        .modal>div{background:#fff;padding:28px;border-radius:6px;max-width:420px}
        .cal{border:1px solid #888;background:#fff;padding:8px;position:absolute;z-index:50}
        .cal button{margin:2px;padding:4px 6px;min-width:34px}"""
        return HTMLResponse(f"<!doctype html><html><head><title>{html.escape(title)}</title>"
                            f"<style>{css}</style></head><body><header>{html.escape(portal)}</header>"
                            f"<main>{body}</main></body></html>")

    def who(request: Request, portal: str):
        tok = request.cookies.get(f"{portal}_session")
        s = st.sessions.get(tok)
        if not s or s[0] != portal:
            return None, tok
        if portal == "summit" and st.summit_live.get(s[1]) != tok:
            return None, tok  # kicked by a newer session
        return s[1], tok

    def login_ok(portal, username, password):
        for c in CREDENTIALS[portal]:
            if c["username"] == username:
                if portal == "summit":
                    return SUMMIT_REAL_PASSWORDS.get(username) == password
                return c["password"] == password
        return False

    def eligible(member_id: str, dob: str | None = None, last: str | None = None):
        c = st.members.get(member_id)
        if not c:
            return None
        if dob and c["patient"]["dob"] != dob:
            return None
        if last and c["patient"]["last_name"].lower() != last.strip().lower():
            return None
        return c

    def record(portal, user, fields: dict, files: list, case):
        ref = {"northwind": "NW", "keystone": "KC", "summit": "SFB-T", "lakeshore": "LS"}[portal] + "-" + str(
            rng.randint(100000, 999999))
        st.submissions.append({"portal": portal, "user": user, "ref": ref, "fields": fields,
                               "files": files, "case_id": case["case_id"] if case else None,
                               "ts": time.time()})
        return ref

    def confirmation(portal, ref, case, fields):
        p = case["patient"]
        return (f"<h2 id='confirm-title'>Request submitted</h2>"
                f"<p>Reference Number: <b id='ref'>{ref}</b></p>"
                f"<p>Patient: <span id='conf-patient'>{p['first_name']} {p['last_name']}</span></p>"
                f"<p>Member ID: <span id='conf-member'>{p['member_id']}</span></p>"
                f"<p>Services: <span id='conf-cpt'>{html.escape(', '.join(fields.get('cpt', [])))}</span></p>"
                f"<p>Status: Pending review</p>")

    # ================================================================ NORTHWIND
    @app.get("/northwind/login")
    def nw_login(err: str = ""):
        e = f"<p class='err'>{html.escape(err)}</p>" if err else ""
        return page("Northwind Provider Portal - Sign in", f"""<h2>Provider sign in</h2>{e}
        <form method='post' action='/northwind/login'>
        <label for='username'>Username</label><input id='username' name='username'>
        <label for='password'>Password</label><input id='password' name='password' type='password'>
        <button id='signin' type='submit'>Sign in</button></form>""", "Northwind Health Plan")

    @app.post("/northwind/login")
    def nw_login_post(username: str = Form(""), password: str = Form("")):
        if not login_ok("northwind", username, password):
            return RedirectResponse("/northwind/login?err=Invalid+username+or+password", 303)
        tok = secrets.token_hex(8)
        st.sessions[tok] = ("northwind", username)
        r = RedirectResponse("/northwind/home", 303)
        r.set_cookie("northwind_session", tok)
        return r

    @app.get("/northwind/home")
    def nw_home(request: Request):
        user, _ = who(request, "northwind")
        if not user:
            return RedirectResponse("/northwind/login", 303)
        modal = ""
        if rng.random() < chaos.survey_modal_rate:
            modal = ("<div class='modal' id='survey-modal' role='dialog'><div><h3>Tell us how we're doing"
                     "</h3><p>Take a 2-minute survey about the provider portal.</p>"
                     "<button id='survey-yes'>Take survey</button> <button id='survey-no'>No thanks</button>"
                     "</div></div><script>document.getElementById('survey-no').onclick=()=>"
                     "document.getElementById('survey-modal').remove();</script>")
        return page("Northwind - Home", f"""<h2>Welcome, {html.escape(user)}</h2>
        <p><a id='new-auth' href='/northwind/new'>New Prior Authorization</a></p>
        <p><a href='/northwind/status'>Check authorization status</a></p>{modal}""", "Northwind Health Plan")

    NW_V2 = {"member_id": ("subscriber_id", "Subscriber ID"), "dob": ("birth_date", "Date of birth"),
             "service_type": ("benefit", "Benefit category"), "cpt": ("hcpcs", "Procedure / HCPCS codes"),
             "icd": ("dx_codes", "ICD-10 diagnoses"), "units": ("qty", "Units / visits"),
             "start": ("from_dt", "Service start"), "end": ("to_dt", "Service end"),
             "npi": ("treating_npi", "Treating provider NPI"), "docs": ("attachments", "Supporting records")}

    def nw_v2_form(e: str) -> str:
        req = chaos.northwind_release == "v2-required"
        f = {k: v for k, v in NW_V2.items()}
        sel = (f"<label for='{f['service_type'][0]}'>{f['service_type'][1]}</label><select id='{f['service_type'][0]}' "
               f"name='{f['service_type'][0]}'><option value=''>Select...</option><option value='aba'>Applied Behavior "
               "Analysis</option><option value='physical_therapy'>Physical Therapy</option><option value='behavioral_health'>"
               "Outpatient Behavioral Health</option></select>")
        inp = lambda k, t="text": f"<label for='{f[k][0]}'>{f[k][1]}</label><input id='{f[k][0]}' name='{f[k][0]}' type='{t}'>"  # noqa: E731
        pos = ("<label for='pos'>Place of service" + ("" if req else " (optional)") + "</label><select id='pos' name='pos'>"
               "<option value=''>--</option><option value='11'>Office</option><option value='12'>Home</option>"
               "<option value='03'>School</option><option value='02'>Telehealth</option></select>")
        return f"""<h2>Request a service authorization</h2>{e}
        <form method='post' action='/northwind/new' enctype='multipart/form-data'>
        {inp('member_id')}{inp('dob', 'date')}{sel}{inp('npi')}{inp('start', 'date')}{inp('end', 'date')}
        {inp('icd')}{inp('cpt')}{inp('units', 'number')}{pos}
        <label for='attachments'>Supporting records</label><input id='attachments' name='attachments' type='file' multiple>
        <button id='nw-send' type='submit'>Send for review</button></form>"""

    @app.get("/northwind/new")
    def nw_new(request: Request, err: str = ""):
        user, _ = who(request, "northwind")
        if not user:
            return RedirectResponse("/northwind/login", 303)
        e = f"<p class='err' id='form-error'>{html.escape(err)}</p>" if err else ""
        if chaos.northwind_release:
            return page("Northwind - Service Authorization", nw_v2_form(e), "Northwind Health Plan")
        return page("Northwind - New Prior Authorization", f"""<h2>New Prior Authorization</h2>{e}
        <form method='post' action='/northwind/new' enctype='multipart/form-data'>
        <label for='member_id'>Member ID</label><input id='member_id' name='member_id'>
        <label for='dob'>Patient Date of Birth</label><input id='dob' name='dob' type='date'>
        <label for='service_type'>Service Type</label><select id='service_type' name='service_type'>
          <option value=''>Select...</option><option value='aba'>Applied Behavior Analysis</option>
          <option value='physical_therapy'>Physical Therapy</option>
          <option value='behavioral_health'>Outpatient Behavioral Health</option></select>
        <label for='cpt'>CPT Codes (comma separated)</label><input id='cpt' name='cpt'>
        <label for='icd'>Diagnosis Codes (ICD-10)</label><input id='icd' name='icd'>
        <label for='units'>Units Requested</label><input id='units' name='units' type='number'>
        <label for='start'>Start Date</label><input id='start' name='start' type='date'>
        <label for='end'>End Date</label><input id='end' name='end' type='date'>
        <label for='npi'>Rendering Provider NPI</label><input id='npi' name='npi'>
        <label for='docs'>Clinical Documents</label><input id='docs' name='docs' type='file' multiple>
        <button id='submit-request' type='submit'>Submit Request</button></form>""", "Northwind Health Plan")

    @app.post("/northwind/new")
    async def nw_new_post(request: Request):
        user, _ = who(request, "northwind")
        if not user:
            return RedirectResponse("/northwind/login", 303)
        form = await request.form()
        if chaos.northwind_release:
            f = {k: form.get(NW_V2[k][0], "") for k in ["member_id", "dob", "service_type", "cpt", "icd", "units",
                                                         "start", "end", "npi"]}
            files = [u.filename for u in form.getlist("attachments") if getattr(u, "filename", "")]
            if chaos.northwind_release == "v2-required" and not form.get("pos"):
                return RedirectResponse("/northwind/new?err=Place+of+service+is+required", 303)
        else:
            f = {k: form.get(k, "") for k in ["member_id", "dob", "service_type", "cpt", "icd", "units",
                                             "start", "end", "npi"]}
            files = [u.filename for u in form.getlist("docs") if getattr(u, "filename", "")]
        case = eligible(f["member_id"].strip(), f["dob"])
        if not case:
            return RedirectResponse("/northwind/new?err=Member+not+found+or+date+of+birth+does+not+match", 303)
        missing = [k for k, v in f.items() if not str(v).strip()]
        if missing or not files:
            return RedirectResponse(f"/northwind/new?err=Missing+required+fields:+{'+'.join(missing or ['docs'])}", 303)
        fields = dict(f, cpt=[c.strip() for c in f["cpt"].split(",") if c.strip()],
                      icd=[c.strip() for c in f["icd"].split(",") if c.strip()])
        ref = record("northwind", user, fields, files, case)
        return page("Northwind - Submitted", confirmation("northwind", ref, case, fields), "Northwind Health Plan")

    # ================================================================ KEYSTONE
    @app.get("/keystone/login")
    def ks_login(err: str = ""):
        e = f"<p class='err'>{html.escape(err)}</p>" if err else ""
        return page("Keystone Medicaid - Login", f"""<h2>Keystone Provider Access</h2>{e}
        <form method='post' action='/keystone/login'>
        <label for='user'>User ID</label><input id='user' name='user'>
        <label for='pass'>Password</label><input id='pass' name='pass' type='password'>
        <button id='login-btn'>Log in</button></form>""", "Keystone Community Medicaid")

    @app.post("/keystone/login")
    def ks_login_post(user: str = Form(""), pass_: str = Form("", alias="pass")):
        if not login_ok("keystone", user, pass_):
            return RedirectResponse("/keystone/login?err=Login+failed", 303)
        tok = secrets.token_hex(8)
        st.sessions[tok] = ("keystone", user)
        r = RedirectResponse("/keystone/portal", 303)
        r.set_cookie("keystone_session", tok)
        return r

    @app.get("/keystone/portal")
    def ks_portal(request: Request):
        user, _ = who(request, "keystone")
        if not user:
            return RedirectResponse("/keystone/login", 303)
        notice = (f"<div id='session-notice' class='modal' role='dialog' style='display:none'><div>"
                  f"<h3>Important notice</h3><p>Scheduled maintenance Sunday 2am-4am.</p>"
                  f"<button id='ack-notice'>Acknowledge</button></div></div><script>setTimeout(()=>"
                  f"{{document.getElementById('session-notice').style.display='flex'}},"
                  f"{chaos.session_notice_delay_ms});document.getElementById('ack-notice').onclick=()=>"
                  f"document.getElementById('session-notice').remove();</script>")
        return page("Keystone - Authorization Requests", f"""<h2>Authorization Requests</h2>
        <iframe id='request-frame' src='/keystone/frame/request' style='width:100%;height:1400px;border:1px solid #ccc'>
        </iframe>{notice}""", "Keystone Community Medicaid")

    CAL_JS = """<script>
    function openCal(id){const box=document.getElementById(id+'-cal');box.style.display='block';
      render(id);}
    function render(id){const box=document.getElementById(id+'-cal');const m=+box.dataset.m,y=+box.dataset.y;
      const names=['January','February','March','April','May','June','July','August','September','October','November','December'];
      let h=`<div><button type=button class='cal-prev' onclick="shift('${id}',-1)">&lt;</button>
      <span class='cal-title'>${names[m]} ${y}</span><button type=button class='cal-next' onclick="shift('${id}',1)">&gt;</button>
      <select class='cal-year' onchange="setY('${id}',this.value)">`;
      for(let yy=1950;yy<=2030;yy++)h+=`<option ${yy==y?'selected':''}>${yy}</option>`;
      h+=`</select></div>`;const days=new Date(y,m+1,0).getDate();
      for(let d=1;d<=days;d++)h+=`<button type=button class='cal-day' data-day='${d}' onclick="pick('${id}',${d})">${d}</button>`;
      box.innerHTML=h;}
    function shift(id,k){const b=document.getElementById(id+'-cal');let m=+b.dataset.m+k,y=+b.dataset.y;
      if(m<0){m=11;y--}if(m>11){m=0;y++}b.dataset.m=m;b.dataset.y=y;render(id);}
    function setY(id,v){document.getElementById(id+'-cal').dataset.y=v;render(id);}
    function pick(id,d){const b=document.getElementById(id+'-cal');const m=+b.dataset.m+1,y=b.dataset.y;
      const iso=`${y}-${String(m).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
      document.getElementById(id).value=iso;document.getElementById(id+'-display').value=`${String(m).padStart(2,'0')}/${String(d).padStart(2,'0')}/${y}`;
      b.style.display='none';}
    function maskMember(el){let v=el.value.toUpperCase().replace(/[^A-Z0-9]/g,'');
      if(v.length>3)v=v.slice(0,3)+'-'+v.slice(3,11);el.value=v;}
    function toggleAba(v){document.getElementById('aba-extra').style.display=v==='aba'?'block':'none';}
    </script>"""

    def cal_field(fid, label):
        today = date.today()
        return (f"<label for='{fid}-display'>{label}</label><input id='{fid}-display' readonly "
                f"placeholder='MM/DD/YYYY' onclick=\"openCal('{fid}')\" aria-label='{label}'>"
                f"<input type='hidden' id='{fid}' name='{fid}'><div id='{fid}-cal' class='cal' "
                f"data-m='{today.month - 1}' data-y='{today.year}' style='display:none'></div>")

    @app.get("/keystone/frame/request")
    def ks_frame(request: Request, err: str = ""):
        user, _ = who(request, "keystone")
        if not user:
            return HTMLResponse("<p>Session expired</p>")
        e = f"<p class='err' id='form-error'>{html.escape(err)}</p>" if err else ""
        return HTMLResponse(f"""<html><head><style>label{{display:block;margin-top:10px;font-weight:600}}
        input,select{{padding:5px}}.cal{{border:1px solid #888;background:#fff;padding:6px}}
        .err{{color:#b00020}}</style></head><body>{CAL_JS}<h3>Submit a Service Authorization</h3>{e}
        <form method='post' action='/keystone/frame/request' enctype='multipart/form-data'>
        <label for='member'>Medicaid ID</label><input id='member' name='member' oninput='maskMember(this)'
          placeholder='XXX-XXXXXXXX' maxlength='12'>
        {cal_field('dob', 'Member Date of Birth')}
        <label for='svc'>Service Category</label><select id='svc' name='svc' onchange='toggleAba(this.value)'>
          <option value=''>-- choose --</option><option value='aba'>ABA Therapy</option>
          <option value='physical_therapy'>Physical Therapy</option>
          <option value='behavioral_health'>Behavioral Health Outpatient</option></select>
        <label for='proc'>Procedure Codes</label><input id='proc' name='proc'>
        <label for='dx'>Primary and Secondary Diagnosis</label><input id='dx' name='dx'>
        <label for='qty'>Total Units</label><input id='qty' name='qty'>
        {cal_field('from', 'Service From')}{cal_field('thru', 'Service Through')}
        <label for='prov'>Servicing Provider NPI</label><input id='prov' name='prov'>
        <div id='aba-extra' style='display:none'>
          <label for='school'>Is a school schedule attached?</label><select id='school' name='school'>
          <option value=''>--</option><option value='yes'>Yes</option><option value='no'>No</option></select>
          <label for='school_hours'>Requested hours on school days</label><input id='school_hours' name='school_hours'>
        </div>
        <label for='attach'>Attachments</label><input id='attach' name='attach' type='file' multiple>
        <button id='ks-submit' type='submit'>Submit Authorization</button></form></body></html>""")

    @app.post("/keystone/frame/request")
    async def ks_frame_post(request: Request):
        user, _ = who(request, "keystone")
        if not user:
            return HTMLResponse("<p>Session expired</p>")
        form = await request.form()
        f = {k: str(form.get(k, "")) for k in ["member", "dob", "svc", "proc", "dx", "qty", "from",
                                               "thru", "prov", "school", "school_hours"]}
        files = [u.filename for u in form.getlist("attach") if getattr(u, "filename", "")]
        if not re.fullmatch(r"[A-Z]{3}-\d{8}", f["member"]):
            return RedirectResponse("/keystone/frame/request?err=Medicaid+ID+must+be+formatted+XXX-XXXXXXXX", 303)
        case = eligible(f["member"].replace("-", ""), f["dob"])
        if not case:
            return RedirectResponse("/keystone/frame/request?err=Member+not+eligible+on+date+of+birth+given", 303)
        req = ["svc", "proc", "dx", "qty", "from", "thru", "prov"]
        if f["svc"] == "aba":
            req += ["school", "school_hours"]
        missing = [k for k in req if not f[k].strip()]
        if missing or not files:
            return RedirectResponse(f"/keystone/frame/request?err=Required:+{'+'.join(missing or ['attach'])}", 303)
        fields = {"member_id": f["member"].replace("-", ""), "dob": f["dob"], "service_type": f["svc"],
                  "cpt": [c.strip() for c in re.split(r"[,\s]+", f["proc"]) if c.strip()],
                  "icd": [c.strip() for c in re.split(r"[,\s]+", f["dx"]) if c.strip()],
                  "units": f["qty"], "start": f["from"], "end": f["thru"], "npi": f["prov"],
                  "school": f["school"], "school_hours": f["school_hours"]}
        ref = record("keystone", user, fields, files, case)
        return HTMLResponse(confirmation("keystone", ref, case, fields))

    # ================================================================ SUMMIT
    @app.get("/summit/login")
    def sm_login(err: str = "", reason: str = ""):
        msg = err or ("Your session ended because you signed in elsewhere." if reason == "session_ended" else "")
        e = f"<p class='err' id='login-error'>{html.escape(msg)}</p>" if msg else ""
        return page("Summit Federal Benefits - Secure Login", f"""<h2>Secure Provider Login</h2>{e}
        <form method='post' action='/summit/login'>
        <label for='login-id'>Login ID</label><input id='login-id' name='login_id'>
        <label for='login-pw'>Password</label><input id='login-pw' name='password' type='password'>
        <button id='continue'>Continue</button></form>""", "Summit Federal Benefits")

    @app.post("/summit/login")
    def sm_login_post(login_id: str = Form(""), password: str = Form("")):
        if login_id in st.summit_locked:
            return RedirectResponse("/summit/login?err=Account+locked.+Contact+your+administrator.", 303)
        if not login_ok("summit", login_id, password):
            st.summit_fail[login_id] = st.summit_fail.get(login_id, 0) + 1
            if st.summit_fail[login_id] >= 3:
                st.summit_locked.add(login_id)
                st.events.append(("lockout", login_id, time.time()))
            return RedirectResponse("/summit/login?err=Invalid+credentials", 303)
        st.summit_fail[login_id] = 0
        tok = secrets.token_hex(8)
        st.summit_pending_mfa[tok] = login_id
        r = RedirectResponse("/summit/mfa", 303)
        r.set_cookie("summit_pre", tok)
        return r

    @app.get("/summit/mfa")
    def sm_mfa(err: str = ""):
        e = f"<p class='err'>{html.escape(err)}</p>" if err else ""
        return page("Summit - Verify", f"""<h2>Two-step verification</h2>{e}
        <p>Enter the 6-digit code from your authenticator app.</p>
        <form method='post' action='/summit/mfa'><label for='otp'>Verification code</label>
        <input id='otp' name='otp' inputmode='numeric' maxlength='6'>
        <button id='verify'>Verify</button></form>""", "Summit Federal Benefits")

    @app.post("/summit/mfa")
    def sm_mfa_post(request: Request, otp: str = Form("")):
        pre = request.cookies.get("summit_pre")
        user = st.summit_pending_mfa.get(pre)
        cred = next((c for c in CREDENTIALS["summit"] if c["username"] == user), None)
        if not cred or not pyotp.TOTP(cred["totp"]).verify(otp, valid_window=1):
            return RedirectResponse("/summit/mfa?err=Invalid+code", 303)
        tok = secrets.token_hex(8)
        st.sessions[tok] = ("summit", user)
        old = st.summit_live.get(user)
        if old:
            st.events.append(("session_kick", user, time.time()))
        st.summit_live[user] = tok
        r = RedirectResponse("/summit/dashboard", 303)
        r.set_cookie("summit_session", tok)
        return r

    def sm_guard(request):
        user, tok = who(request, "summit")
        if not user:
            reason = "session_ended" if st.sessions.get(tok) else ""
            return None, tok, RedirectResponse(f"/summit/login?reason={reason}", 303)
        return user, tok, None

    @app.get("/summit/dashboard")
    def sm_dash(request: Request):
        user, tok, redir = sm_guard(request)
        if redir:
            return redir
        return page("Summit - Dashboard", """<h2>Provider Dashboard</h2>
        <button id='start-request' onclick="location.href='/summit/request/1'">Start a new request</button>""",
                    "Summit Federal Benefits")

    @app.get("/summit/request/{step}")
    def sm_step(step: int, request: Request, err: str = ""):
        user, tok, redir = sm_guard(request)
        if redir:
            return redir
        if step == 2 and not err and rng.random() < chaos.summit_kick_rate:
            st.summit_live[user] = "human-" + secrets.token_hex(4)
            st.events.append(("session_kick", user, time.time()))
            return RedirectResponse("/summit/login?reason=session_ended", 303)
        e = f"<p class='err' id='form-error'>{html.escape(err)}</p>" if err else ""
        hdr = f"<h2>New request - Step {step} of 4</h2>{e}"
        if step == 1:
            body = """<form method='post' action='/summit/request/1'>
            <label for='mem'>Member Number</label><input id='mem' name='mem'>
            <label for='lname'>Member Last Name</label><input id='lname' name='lname'>
            <button id='find-member'>Find member</button></form>"""
        elif step == 2:
            boxes = "".join(f"<label><input type='checkbox' name='cpt' value='{c}' id='cpt-{c}'> {c}</label>"
                            for c in ["97151", "97153", "97155", "97156", "97110", "97140", "97530",
                                      "90834", "90837", "90847"])
            body = f"""<form method='post' action='/summit/request/2'>
            <fieldset><legend>Procedure codes</legend>{boxes}</fieldset>
            <label for='diag'>Diagnosis codes</label><input id='diag' name='diag'>
            <label for='qty'>Quantity</label><input id='qty' name='qty'>
            <label for='dfrom'>From date (MM/DD/YYYY)</label><input id='dfrom' name='dfrom'>
            <label for='dto'>To date (MM/DD/YYYY)</label><input id='dto' name='dto'>
            <label for='rnpi'>Rendering NPI</label><input id='rnpi' name='rnpi'>
            <label for='cont'>Is this a continuation of an existing authorization?</label>
            <select id='cont' name='cont' onchange="document.getElementById('prior-wrap').style.display=this.value==='yes'?'block':'none'">
            <option value=''>Select</option><option value='no'>No</option><option value='yes'>Yes</option></select>
            <div id='prior-wrap' style='display:none'><label for='prior'>Prior authorization number</label>
            <input id='prior' name='prior'></div>
            <label for='inpatient'>Is the member currently admitted inpatient?</label>
            <select id='inpatient' name='inpatient'><option value=''>Select</option><option>No</option><option>Yes</option></select>
            <button id='next-2'>Next</button></form>"""
        elif step == 3:
            body = """<form method='post' action='/summit/request/3' enctype='multipart/form-data'>
            <p>Upload each document and choose its type. PDF only.</p>
            <label for='file1'>Document 1</label><input id='file1' name='file1' type='file' accept='.pdf'>
            <label for='type1'>Document 1 type</label><select id='type1' name='type1'><option value=''>Select</option>
            <option value='treatment_plan'>Treatment plan</option><option value='referral'>Referral</option>
            <option value='clinical_notes'>Clinical notes</option></select>
            <label for='file2'>Document 2 (optional)</label><input id='file2' name='file2' type='file' accept='.pdf'>
            <label for='type2'>Document 2 type</label><select id='type2' name='type2'><option value=''>Select</option>
            <option value='treatment_plan'>Treatment plan</option><option value='referral'>Referral</option>
            <option value='clinical_notes'>Clinical notes</option></select>
            <button id='next-3'>Next</button></form>"""
        else:
            w = st.wizard.get(tok, {})
            rows = "".join(f"<tr><td>{html.escape(k)}</td><td class='rv' data-k='{k}'>{html.escape(str(v))}</td></tr>"
                           for k, v in w.items() if k != "case")
            body = f"""<table id='review'>{rows}</table>
            <form method='post' action='/summit/request/4'><label><input type='checkbox' id='attest' name='attest' value='1'>
            I attest the information is accurate.</label><button id='submit-final'>Submit request</button></form>"""
        return page(f"Summit - Request step {step}", hdr + body, "Summit Federal Benefits")

    @app.post("/summit/request/{step}")
    async def sm_step_post(step: int, request: Request):
        user, tok, redir = sm_guard(request)
        if redir:
            return redir
        form = await request.form()
        w = st.wizard.setdefault(tok, {})
        if step == 1:
            case = eligible(str(form.get("mem", "")).strip(), last=str(form.get("lname", "")))
            if not case:
                return RedirectResponse("/summit/request/1?err=No+eligible+member+found", 303)
            w.clear()
            w.update({"case": case, "member_id": case["patient"]["member_id"]})
            return RedirectResponse("/summit/request/2", 303)
        if step == 2:
            dfrom, dto = str(form.get("dfrom", "")), str(form.get("dto", ""))
            if not all(re.fullmatch(r"\d{2}/\d{2}/\d{4}", d) for d in (dfrom, dto)):
                return RedirectResponse("/summit/request/2?err=Dates+must+be+MM/DD/YYYY", 303)
            cont = str(form.get("cont", ""))
            if cont not in ("yes", "no") or not form.get("inpatient"):
                return RedirectResponse("/summit/request/2?err=Answer+all+required+questions", 303)
            if cont == "yes" and not form.get("prior"):
                return RedirectResponse("/summit/request/2?err=Prior+authorization+number+required", 303)
            cpts = form.getlist("cpt")
            if not cpts:
                return RedirectResponse("/summit/request/2?err=Select+at+least+one+procedure", 303)
            to_iso = lambda d: datetime.strptime(d, "%m/%d/%Y").date().isoformat()  # noqa: E731
            w.update({"cpt": cpts, "icd": [x for x in re.split(r"[,\s]+", str(form.get("diag", ""))) if x],
                      "units": str(form.get("qty", "")), "start": to_iso(dfrom), "end": to_iso(dto),
                      "npi": str(form.get("rnpi", "")), "continuation": cont,
                      "inpatient": str(form.get("inpatient"))})
            return RedirectResponse("/summit/request/3", 303)
        if step == 3:
            files = []
            for i in (1, 2):
                up = form.get(f"file{i}")
                fname = getattr(up, "filename", "") if up is not None else ""
                if not fname:
                    continue
                if not fname.lower().endswith(".pdf"):
                    return RedirectResponse("/summit/request/3?err=Only+PDF+files+are+accepted", 303)
                if not form.get(f"type{i}"):
                    return RedirectResponse(f"/summit/request/3?err=Choose+a+type+for+document+{i}", 303)
                files.append({"name": fname, "type": str(form.get(f"type{i}"))})
            if not files:
                return RedirectResponse("/summit/request/3?err=At+least+one+document+is+required", 303)
            w["files"] = files
            return RedirectResponse("/summit/request/4", 303)
        if not form.get("attest"):
            return RedirectResponse("/summit/request/4?err=Attestation+required", 303)
        if rng.random() < chaos.summit_503_rate:
            return HTMLResponse("<h1>503 Service Temporarily Unavailable</h1><p>Please try again.</p>", 503)
        case = w.pop("case")
        fields = {k: v for k, v in w.items() if k != "files"}
        ref = record("summit", user, fields, [f["name"] for f in w.get("files", [])], case)
        st.wizard.pop(tok, None)
        return page("Summit - Confirmation", confirmation("summit", ref, case, fields), "Summit Federal Benefits")

    # ================================================================ LAKESHORE (held out)
    @app.get("/lakeshore/signin")
    def ls_signin(err: str = ""):
        e = f"<p class='err'>{html.escape(err)}</p>" if err else ""
        return page("Lakeshore Provider Connect", f"""<h2>Log in to Provider Connect</h2>{e}
        <form method='post' action='/lakeshore/signin'>
        <label for='pid'>Provider ID</label><input id='pid' name='pid'>
        <label for='pcode'>Passcode</label><input id='pcode' name='pcode' type='password'>
        <button id='go' type='submit'>Log in</button></form>""", "Lakeshore Health Partners")

    @app.post("/lakeshore/signin")
    def ls_signin_post(pid: str = Form(""), pcode: str = Form("")):
        if not login_ok("lakeshore", pid, pcode):
            return RedirectResponse("/lakeshore/signin?err=We+could+not+verify+that+Provider+ID+and+Passcode", 303)
        tok = secrets.token_hex(8)
        st.sessions[tok] = ("lakeshore", pid)
        r = RedirectResponse("/lakeshore/workqueue", 303)
        r.set_cookie("lakeshore_session", tok)
        return r

    @app.get("/lakeshore/workqueue")
    def ls_queue(request: Request):
        user, _ = who(request, "lakeshore")
        if not user:
            return RedirectResponse("/lakeshore/signin", 303)
        return page("Lakeshore - Work queue", f"""<h2>Work queue for {html.escape(user)}</h2>
        <p><a id='msgs' href='/lakeshore/messages'>Messages (3)</a></p>
        <p><a id='elig' href='/lakeshore/eligibility'>Eligibility and benefits</a></p>
        <p><a id='start' href='/lakeshore/request/lookup'>Start a utilization review request</a></p>""",
                    "Lakeshore Health Partners")

    @app.get("/lakeshore/request/lookup")
    def ls_lookup(request: Request, err: str = ""):
        user, _ = who(request, "lakeshore")
        if not user:
            return RedirectResponse("/lakeshore/signin", 303)
        e = f"<p class='err' id='form-error'>{html.escape(err)}</p>" if err else ""
        return page("Lakeshore - Find patient", f"""<h2>Step 1 of 2: Find the patient</h2>{e}
        <form method='post' action='/lakeshore/request/lookup'>
        <label for='sub'>Subscriber number</label><input id='sub' name='sub'>
        <label for='bd'>Birthdate (MM/DD/YYYY)</label><input id='bd' name='bd' placeholder='MM/DD/YYYY'>
        <label for='ln'>Patient last name</label><input id='ln' name='ln'>
        <button id='find' type='submit'>Find patient</button></form>""", "Lakeshore Health Partners")

    @app.post("/lakeshore/request/lookup")
    def ls_lookup_post(request: Request, sub: str = Form(""), bd: str = Form(""), ln: str = Form("")):
        user, tok = who(request, "lakeshore")
        if not user:
            return RedirectResponse("/lakeshore/signin", 303)
        try:
            iso = datetime.strptime(bd.strip(), "%m/%d/%Y").date().isoformat()
        except ValueError:
            return RedirectResponse("/lakeshore/request/lookup?err=Birthdate+must+be+MM/DD/YYYY", 303)
        case = eligible(sub.strip(), iso, ln)
        if not case:
            return RedirectResponse("/lakeshore/request/lookup?err=No+matching+subscriber", 303)
        st.lookup[tok] = case
        return RedirectResponse("/lakeshore/request/details", 303)

    @app.get("/lakeshore/request/details")
    def ls_details(request: Request, err: str = ""):
        user, tok = who(request, "lakeshore")
        if not user:
            return RedirectResponse("/lakeshore/signin", 303)
        case = st.lookup.get(tok)
        if not case:
            return RedirectResponse("/lakeshore/request/lookup", 303)
        e = f"<p class='err' id='form-error'>{html.escape(err)}</p>" if err else ""
        p = case["patient"]
        return page("Lakeshore - Request details", f"""<h2>Step 2 of 2: Request details</h2>{e}
        <p>Patient: {html.escape(p['first_name'])} {html.escape(p['last_name'])}</p>
        <form method='post' action='/lakeshore/request/details' enctype='multipart/form-data'>
        <label for='prog'>Program</label><select id='prog' name='prog'><option value=''>Choose a program</option>
          <option value='ABA'>ABA Therapy</option><option value='PTOT'>PT / OT Rehabilitation</option>
          <option value='MHO'>Mental Health Outpatient</option></select>
        <label for='proc'>Procedure codes (CPT/HCPCS)</label><input id='proc' name='proc'>
        <label for='dx'>Primary and secondary diagnoses (ICD-10)</label><input id='dx' name='dx'>
        <label for='qty'>Quantity (units)</label><input id='qty' name='qty' type='number'>
        <label for='sfrom'>Service from</label><input id='sfrom' name='sfrom' type='date'>
        <label for='sthru'>Service through</label><input id='sthru' name='sthru' type='date'>
        <label for='rnpi'>Rendering clinician NPI</label><input id='rnpi' name='rnpi'>
        <label for='att'>Supporting documentation</label><input id='att' name='att' type='file' multiple>
        <label><input type='checkbox' id='attest' name='attest' value='yes'> I attest that this information is
          accurate and complete</label>
        <button id='draft' name='action' value='draft' type='submit'>Save draft</button>
        <button id='send' name='action' value='send' type='submit'>Send to Utilization Review</button>
        </form>""", "Lakeshore Health Partners")

    @app.post("/lakeshore/request/details")
    async def ls_details_post(request: Request):
        user, tok = who(request, "lakeshore")
        if not user:
            return RedirectResponse("/lakeshore/signin", 303)
        case = st.lookup.get(tok)
        if not case:
            return RedirectResponse("/lakeshore/request/lookup", 303)
        form = await request.form()
        if form.get("action") == "draft":
            st.events.append({"portal": "lakeshore", "event": "draft_saved", "ts": time.time()})
            return RedirectResponse("/lakeshore/request/details?err=Draft+saved.+The+request+has+NOT+been+sent", 303)
        f = {k: form.get(k, "") for k in ["prog", "proc", "dx", "qty", "sfrom", "sthru", "rnpi"]}
        files = [u.filename for u in form.getlist("att") if getattr(u, "filename", "")]
        missing = [k for k, v in f.items() if not str(v).strip()] + ([] if files else ["att"])
        if missing:
            return RedirectResponse(f"/lakeshore/request/details?err=Required:+{'+'.join(missing)}", 303)
        if form.get("attest") != "yes":
            return RedirectResponse("/lakeshore/request/details?err=Please+attest+before+sending", 303)
        prog = {"ABA": "aba", "PTOT": "physical_therapy", "MHO": "behavioral_health"}.get(f["prog"])
        if prog != case["specialty"]:
            return RedirectResponse("/lakeshore/request/details?err=Program+does+not+match+the+request", 303)
        fields = {"member_id": case["patient"]["member_id"], "service_type": prog, "units": f["qty"],
                  "start": f["sfrom"], "end": f["sthru"], "npi": f["rnpi"],
                  "cpt": [c.strip() for c in f["proc"].split(",") if c.strip()],
                  "icd": [c.strip() for c in f["dx"].split(",") if c.strip()]}
        ref = record("lakeshore", user, fields, files, case)
        st.lookup.pop(tok, None)
        return page("Lakeshore - Sent", confirmation("lakeshore", ref, case, fields), "Lakeshore Health Partners")

    # ================================================================ FHIR (CMS-0057-F)
    @app.post("/fhir/Claim/$submit")
    async def fhir_submit(request: Request):
        bundle = await request.json()
        claim = next((e["resource"] for e in bundle.get("entry", [])
                      if e["resource"].get("resourceType") == "Claim"), None)
        if not claim or claim.get("use") != "preauthorization":
            return JSONResponse({"resourceType": "OperationOutcome", "issue": [
                {"severity": "error", "code": "invalid", "diagnostics": "Bundle must contain a preauthorization Claim"}]}, 400)
        ref_ = claim.get("patient", {})
        if "reference" in ref_:   # R4: the claim points at the Patient in the bundle
            pat = next((e["resource"] for e in bundle.get("entry", []) if e.get("fullUrl") == ref_["reference"]), {})
            member = next((i.get("value") for i in pat.get("identifier", [])), None)
        else:
            member = ref_.get("identifier", {}).get("value")
        case = st.members.get(member)
        if not case:
            return JSONResponse({"resourceType": "OperationOutcome", "issue": [
                {"severity": "error", "code": "not-found", "diagnostics": "Member not found"}]}, 404)
        ref = "HBL-" + str(rng.randint(100000, 999999))
        items = [i["productOrService"]["coding"][0]["code"] for i in claim.get("item", [])]
        st.submissions.append({"portal": "fhir", "user": "api", "ref": ref, "case_id": case["case_id"],
                               "fields": {"member_id": member, "cpt": items}, "files": [], "ts": time.time()})
        return JSONResponse({"resourceType": "ClaimResponse", "status": "active", "use": "preauthorization",
                             "outcome": "queued", "preAuthRef": ref,
                             "patient": claim.get("patient"), "created": datetime.utcnow().isoformat()})

    @app.get("/_admin/submissions")
    def admin_subs():
        return st.submissions

    @app.get("/_admin/events")
    def admin_events():
        return st.events

    return app
