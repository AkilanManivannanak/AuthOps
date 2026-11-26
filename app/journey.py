"""Prior authorizations, one patient at a time, on the shared workspace.

Every step changes the patient's record, so Today, Insurance monitoring and the suggestions follow along.
"""
from __future__ import annotations

import json
import random
import tempfile
from datetime import date
from pathlib import Path

import streamlit as st

from app.account import open_page, save, today, ws
from app.ui import ASSETS, checklist, rule_label
from app.widgets.outlook import approval_outlook
from app.widgets.workbench import workbench
from authops import workspace as W
from authops.docintel.extract import RuleExtractor
from authops.docintel.ocr import ocr_pages
from authops.intel.approval import Request
from authops.schemas import DocType
from authops.validation.rules import validate_case

STEPS = ["Intake", "Readiness check", "Submit", "Payor decision", "Monitoring"]
ROUTE = {"portal": "Browser agent on the payor portal", "fhir": "Payor's electronic prior auth API", "phone": "Phone agent"}
REPLAY = {"KCM": ("keystone_aba_iframe_calendar", "summit_mfa_503_retry"), "NWH": ("northwind_popup", "summit_mfa_503_retry"),
          "SFB": ("summit_mfa_503_retry", "summit_mfa_503_retry")}
CSS = """<style>
.jr-rail{display:flex;margin:.6rem 0 1.4rem;border:1px solid #ECE5D8;border-radius:999px;overflow:hidden;background:#fff}
.jr-rail div{flex:1;padding:10px 6px;text-align:center;font-size:.84rem;color:#8E8292;border-right:1px solid #F0EAE2}
.jr-rail div:last-child{border-right:0}.jr-rail .done{color:#5B2A86;background:#F7F1FB}.jr-rail .cur{color:#fff;background:#1E0525;font-weight:600}
.jr-route{display:inline-flex;gap:8px;align-items:center;border-radius:999px;background:#EFE7FA;color:#5B2A86;font-weight:600;padding:6px 14px;font-size:.9rem}
.jr-chip{display:inline-block;border:1px solid #ECE5D8;border-radius:12px;padding:10px 14px;background:#fff;margin:0 10px 10px 0}
.jr-chip b{display:block;font-family:Fraunces,Georgia,serif;font-weight:400;font-size:1.5rem}.jr-chip span{color:#7A6B80;font-size:.8rem}
.jr-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}.jr-head .n{font-family:Fraunces,Georgia,serif;font-size:1.7rem}
</style>"""


@st.cache_data(show_spinner=False, max_entries=32)
def _read(pages: tuple, doc_type: str):
    ocr = ocr_pages(list(pages))
    ex = RuleExtractor().extract("doc", ocr, DocType(doc_type))
    return {"fields": {k: v.model_dump() for k, v in ex.fields.items()},
            "words": [(w.text, w.conf, w.box, pi) for pi, p in enumerate(ocr.pages) for w in p.words], "text": ocr.text}


def _plan_pages(p: dict) -> list[str]:
    key = ("plan", p["id"], json.dumps(p.get("mods", {}), sort_keys=True), p["units"])
    cache = st.session_state.setdefault("_jr_pages", {})
    if key not in cache:
        from authops.synth.render import render_treatment_plan, save_doc
        rng = random.Random(p["seed"])
        cache[key] = save_doc(render_treatment_plan(W.case_for(p), rng, False), Path(tempfile.mkdtemp()), "tp", "fax", rng)
    return cache[key]


def _letter_pages(p: dict) -> list[str]:
    key = ("letter", p["id"], p["stage"], p.get("approved"))
    cache = st.session_state.setdefault("_jr_pages", {})
    if key not in cache:
        import authops.synth.render as R
        orig, dec = R.payor_decision, p["stage"]
        R.payor_decision = lambda case, rng: (dec, p.get("approved") or 0, p.get("denial"))
        try:
            rng = random.Random(p["seed"] + 1)
            w, _, _ = R.render_letter(W.case_for(p), rng)
            cache[key] = R.save_doc(w, Path(tempfile.mkdtemp()), "letter", "fax", rng)
        finally:
            R.payor_decision = orig
    return cache[key]


def _fields(res: dict, thr: float = 0.55) -> list[dict]:
    out = []
    for name, fv in res["fields"].items():
        if name == "denial_reason":
            continue
        v, conf = fv["value"], fv["confidence"]
        status = "abstained" if (v in (None, "", []) or conf < thr) else ("sure" if conf >= 0.8 else "unsure")
        sv = None if v in (None, "", []) else str(", ".join(v) if isinstance(v, list) else v)
        boxes = []
        if sv:
            toks = {x.strip(",.:").upper() for x in sv.split()}
            if len(sv) == 10 and sv[4] == "-":
                d = date.fromisoformat(sv)
                toks |= {d.strftime("%m/%d/%Y"), d.strftime("%B").upper(), f"{d.day},", str(d.year)}
            boxes = [w[2] for w in res["words"] if w[3] == 0 and w[0].strip(",.:").upper() in toks and len(w[0]) > 1][:6]
        out.append({"key": name, "label": name.replace("_", " "), "value": None if status == "abstained" else sv,
                    "conf": float(conf), "status": status, "boxes": boxes,
                    "why": {"sure": "Read with high confidence.", "unsure": "Filled in; worth a glance.",
                            "abstained": "Too unsure to guess, so it is left for you."}[status]})
    return out


def _rail(step: int) -> None:
    cells = "".join(f"<div class='{'done' if k < step else 'cur' if k == step else ''}'><b>{'✓' if k < step else k + 1}</b>&nbsp;{n}</div>"
                    for k, n in enumerate(STEPS))
    st.markdown(f"<div class='jr-rail'>{cells}</div>", unsafe_allow_html=True)


def _step_of(p: dict) -> int:
    v = st.session_state.setdefault("_jr_view", {}).get(p["id"])
    base = {"intake": 0, "check": 1, "ready": 1, "submitted": 2, "approved": 3, "partial": 3, "denied": 3}[p["stage"]]
    return v if v is not None and v <= max(base, 4 if p["stage"] in ("approved", "partial") else base) else base


def _view(pid: str, k: int | None) -> None:
    st.session_state.setdefault("_jr_view", {})[pid] = k


def journey() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    w, t = ws(), today()
    order = {"check": 0, "denied": 1, "ready": 2, "intake": 3, "submitted": 4, "partial": 5, "approved": 6}
    pats = sorted(w["patients"], key=lambda p: (order[p["stage"]], p["name"]))
    ids = [p["id"] for p in pats]
    focus = st.session_state.get("focus")
    if focus not in ids:
        sug = W.suggestions(w, t, 5)
        focus = next((s["pid"] for s in sug if s.get("pid") in ids and s["page"] == "prior_authorizations"), ids[0])
    pid = st.selectbox("Patient", ids, index=ids.index(focus), key=f"jr_pick_{focus}",
                       format_func=lambda i: f"{W.find(w, i)['name']} · {W.status(W.find(w, i), w, t)['label']}")
    st.session_state.focus = pid
    p = W.find(w, pid)
    st.markdown(f"<div class='jr-head'><span class='n'>{p['name']}</span><span class='ao-muted'>{W.SERVICE[p['spec']]} · "
                f"{p['payor_name']} · {p['units']} {p['unit']} asked</span></div>", unsafe_allow_html=True)
    step = _step_of(p)
    _rail(step)

    # ------------------------------------------------------------ 1 intake
    if step == 0:
        st.markdown("#### The clinic's treatment plan arrived. Here is what was read from it")
        pages = _plan_pages(p)
        res = _read(tuple(pages), DocType.TREATMENT_PLAN.value)
        fields = _fields(res)
        workbench(pages[0], [x[2] for x in res["words"] if x[3] == 0], fields,
                  f"{sum(f['status'] != 'abstained' for f in fields)} of {len(fields)} fields read automatically", key=f"jr_wb_{pid}")
        gaps = [f for f in fields if f["status"] == "abstained"]
        typed = 0
        for f in gaps:
            typed += bool(st.text_input(f["label"].capitalize() + " (left for you)", key=f"jr_t_{pid}_{f['key']}"))
        if st.button("Looks right, check it against the payor's rules", type="primary", disabled=typed < len(gaps)):
            msg = W.read(w, pid, t)
            _view(pid, None)
            save(msg)
            st.rerun()
        return

    # ------------------------------------------------------------ 2 readiness
    if step == 1:
        iss = W.issues(p, w, t)
        o = W.outlook(p)
        short = not iss and o["p_full"] < 0.8 and o["recommended"] != p["units"]
        st.markdown("#### Fix anything the payor would deny, before it is sent")
        left, right = st.columns([1, 1.25], gap="large")
        with left:
            for i, it in enumerate(iss):
                st.markdown(f"<div class='ao-card' style='border-color:#F4C9D8;background:#FDF5F8'><b style='color:#A8355F'>"
                            f"{it['text']}</b><div class='ao-muted'>{it['detail']}</div></div>", unsafe_allow_html=True)
                if it["code"] == "units_within_payor_limit":   # the payor's rule, with the rest kept as a second request
                    if st.button(f"Split it: {it['cap']} now, {p['units'] - it['cap']} in a second request",
                                 key=f"jr_split_{pid}_{i}", type="primary"):
                        save(W.split(w, pid, t))
                        st.rerun()
                    if st.button(f"Lower to the payor's limit ({it['cap']} {p['unit']})", key=f"jr_fix_{pid}_{i}"):
                        save(W.fix(w, pid, it["code"], t, value=it["cap"]))
                        st.rerun()
                    continue
                lim = it.get("cap")
                label = W.FIX.get(it["code"], ("Fix it",))[0] + (f" ({lim} {p['unit']})" if lim else "")
                if st.button(label, key=f"jr_fix_{pid}_{i}", type="primary"):
                    save(W.fix(w, pid, it["code"], t, value=lim))
                    st.rerun()
            rep = validate_case(W.case_for(p), t, include_custom=False)
            checklist([("ok" if r.passed else "bad", rule_label(r.rule), r.message or "passes") for r in rep.results if r.passed]
                      + [("warn" if short else "ok", "Amount this payor approves in full",
                          f"{o['p_full']:.0%} chance at {p['units']}; {o['recommended']} gives {o['p_rec']:.0%}" if short
                          else f"{o['p_full']:.0%} chance at {p['units']} {p['unit']}")])
        with right:
            m, rq = W.model(), W._request(p, p["units"])
            hi = max(p["units"], o["recommended"]) + 5
            curve = [{"units": c["units"], "p": c["p_full"], "exp": m.outlook(rq, c["units"])["expected_units"]}
                     for c in m.curve(Request(rq.week, rq.payor, rq.specialty, rq.severity, rq.utilization, rq.first_auth,
                                              rq.doc_score, hi, 1.0), points=40)]
            approval_outlook(curve, [], p["units"], o["recommended"], 0.8, key=f"jr_ol_{pid}_{p['units']}")
            if short and st.button(f"Ask for {o['recommended']} {p['unit']} instead ({o['p_rec']:.0%} chance)", type="primary"):
                W.set_units(w, pid, o["recommended"], t)
                save("Amount updated.")
                st.rerun()
        if not iss and st.button(f"Send to {p['payor_name']}", type="secondary" if short else "primary"):
            save(W.submit(w, pid, t))
            _view(pid, None)
            st.rerun()
        return

    # ------------------------------------------------------------ 3 submitted
    if step == 2:
        ch = W.case_for(p).payor.channel
        st.markdown(f"#### Sent the best way {p['payor_name']} accepts")
        st.markdown(f"<span class='jr-route'>{ROUTE[ch]}</span> &nbsp; <span class='ao-muted'>sent {p.get('submitted_on', '')}</span>",
                    unsafe_allow_html=True)
        if ch == "portal":
            from app.widgets.replay import player
            name = REPLAY.get(p["payor"], REPLAY["NWH"])[0]
            run = json.loads((ASSETS / "replays" / name / "run.json").read_text())
            st.caption(f"How the agent submitted it: {len(run['steps'])} steps on the payor portal, confirmation number read back.")
            player(run, ASSETS / "replays" / name)
        elif ch == "fhir":
            st.markdown("Sent as one structured electronic request. The payor answered **202 Accepted**.")
        else:
            st.markdown("Called the payor's line, worked the phone menu and read the reference number back.")
        if st.button("Check for a decision", type="primary"):
            save(W.receive(w, pid, t))
            _view(pid, None)
            st.rerun()
        return

    # ------------------------------------------------------------ 4 decision
    if step == 3:
        st.markdown("#### The payor's letter came back, and was read the same way")
        pages = _letter_pages(p)
        res = _read(tuple(pages), DocType.APPROVAL_LETTER.value if p["stage"] != "denied" else DocType.DENIAL_LETTER.value)
        word = {"approved": "Approved in full", "partial": f"Approved {p.get('approved')} {p['unit']}", "denied": "Denied"}[p["stage"]]
        workbench(pages[0], [x[2] for x in res["words"] if x[3] == 0], _fields(res), word, key=f"jr_wl_{pid}_{p['stage']}")
        if p["stage"] == "denied":
            a, b = st.columns(2)
            a.markdown("**Correct and resend**  \nAdd what the payor asked for and send again. Usually faster than an appeal.")
            if a.button("Correct and resend", type="primary"):
                p.pop("denial", None)
                p["stage"] = "ready"
                W.activity(w, f"Corrected {p['name']}'s request for resending", "prior_authorizations")
                save("Moved back to Ready to send.")
                st.rerun()
            b.markdown("**Appeal**  \nArgue the decision using quotes from the chart, page by page.")
            if b.button("Draft the appeal"):
                open_page("prior_authorizations", pid, {"tool": "Appeal a denial"})
            return
        if p["stage"] == "partial":
            st.info(f"Cut to {p['approved']} of {p['units']} {p['unit']}. Start care on what was approved and ask for the "
                    "rest at reauthorization; next time the readiness check recommends the amount this payor approves in full.")
        if st.button("Watch it until the next authorization", type="primary"):
            _view(pid, 4)
            st.rerun()
        return

    # ------------------------------------------------------------ 5 monitoring
    r = W.runway(p, t) or {}
    st.markdown("#### Cleared for care. Watched until the next authorization")
    st.markdown(f"<span class='jr-chip'><b>{p.get('approved')}</b><span>{p['unit']} approved</span></span>"
                f"<span class='jr-chip'><b>{r.get('units_left', '')}</b><span>{p['unit']} left</span></span>"
                f"<span class='jr-chip'><b>{r.get('runway_days', '')} days</b><span>of care left</span></span>"
                f"<span class='jr-chip'><b>{date.fromisoformat(r['reauth_on']):%b %d}</b><span>start the reauthorization</span></span>"
                if r else "", unsafe_allow_html=True)
    if st.button("Open in Insurance monitoring", type="primary"):
        open_page("insurance_monitoring", pid)
