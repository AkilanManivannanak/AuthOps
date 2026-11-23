import streamlit as st

from app.ui import asset_json, proof_cards, setup, store, tiles

setup("Prior auths, cleared before care starts", "26 weeks of requests through the real pipeline. Click anything.")

m = asset_json("metrics.json") or {}
ex = (m.get("extraction", {}).get("arms", {}).get("rules", {}) or {}).get("summary", {}).get("all", {})
val = m.get("validation", {})
ag = m.get("agents", {}).get("all", {})
abl = m.get("ablations", {})
cal = m.get("calibration", {})
c = store().counts()


# ---------------------------------------------------------------- operations floor
from app.floor import operations_floor  # noqa: E402
from authops.sim.floor import build as build_floor  # noqa: E402


@st.cache_data(show_spinner="Running 26 weeks of requests through the pipeline")
def _floor():
    return build_floor()


operations_floor(_floor())

# ---------------------------------------------------------------- live request
import random  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402

from authops.docintel.extract import RuleExtractor  # noqa: E402
from authops.docintel.ocr import ocr_pages  # noqa: E402
from authops.schemas import DocType  # noqa: E402
from authops.synth.generate import generate_cases, payor_decision  # noqa: E402
from authops.synth.render import render_treatment_plan, save_doc  # noqa: E402
from authops.validation.rules import validate_case  # noqa: E402

TODAY = date(2026, 11, 17)
_demo = Path(__file__).resolve().parents[2] / "docs" / "media" / "demo.mp4"
if _demo.exists():
    with st.expander("▶  Watch the tour", expanded=False):
        st.video(str(_demo))
st.markdown("### Run one request yourself")
k1, k2, k3 = st.columns([1.2, 1, 1])
go = k1.button("▶  Run a request", type="primary", width="stretch")
gap = k2.toggle("Inject a documentation gap", help="Removes the provider signature so you can watch the rules catch it.")
cond = k3.segmented_control("Document quality", ["clean", "scan", "fax"], default="scan", label_visibility="collapsed")


@st.cache_resource(show_spinner=False)
def _outlook_model():
    from authops.intel.approval import ApprovalModel, history_from, simulate
    return ApprovalModel().fit([h for h in history_from(simulate(), random.Random(8)) if h[0].week < 40])


def _chip(name, fv):
    if fv.abstained or fv.value is None:
        cls, val = "ao-bad", "abstained"
    else:
        cls, val = ("ao-ok" if fv.confidence >= 0.85 else "ao-warn"), str(fv.value)[:22]
    return (f"<span class='ao-pill {cls}' style='margin:2px 4px 2px 0' title='confidence {fv.confidence:.2f}'>"
            f"{name.replace('_', ' ')}: {val}</span>")


if go:
    seed = random.randint(1, 99999)
    case = generate_cases(1, seed=seed, today=TODAY, gap_rate=0.0)[0]
    if gap:
        case.signature_present, case.signature_date = False, None
    rng = random.Random(seed)
    st.markdown(f"<div class='ao-card ao-rise'><b>{case.patient.full_name}</b> &nbsp;·&nbsp; {case.payor.name} &nbsp;·&nbsp; "
                f"{case.specialty.replace('_', ' ')} &nbsp;·&nbsp; {case.requested_units} units requested</div>",
                unsafe_allow_html=True)
    with st.status("📄 Reading the treatment plan", expanded=True) as s1:
        d = Path(tempfile.mkdtemp())
        pages = save_doc(render_treatment_plan(case, rng, False), d, "tp", cond or "scan", rng)
        ocr = ocr_pages(pages)
        tp_ex = RuleExtractor().extract("tp", ocr, DocType.TREATMENT_PLAN)
        c1, c2 = st.columns([1, 2])
        c1.image(pages[0], width="stretch")
        c2.markdown("".join(_chip(k, v) for k, v in tp_ex.fields.items()), unsafe_allow_html=True)
        c2.caption(f"OCR confidence {ocr.mean_conf:.0f} · {sum(not v.abstained for v in tp_ex.fields.values())} of "
                   f"{len(tp_ex.fields)} fields filled")
        s1.update(label=f"📄 Read: {sum(not v.abstained for v in tp_ex.fields.values())}/{len(tp_ex.fields)} fields",
                  state="complete")
    with st.status("🛡️ Checking payor rules", expanded=True) as s2:
        time.sleep(0.3)
        rep = validate_case(case, TODAY, include_custom=False)
        st.markdown("".join(f"<span class='ao-pill {'ao-ok' if r.passed else 'ao-bad'}' style='margin:2px 4px 2px 0'>"
                            f"{'✓' if r.passed else '✗'} {r.rule.replace('_', ' ')}</span>" for r in rep.results),
                    unsafe_allow_html=True)
        s2.update(label="🛡️ Rules: ready" if rep.ready else f"🛡️ Rules: blocked ({len(rep.blocking)})",
                  state="complete" if rep.ready else "error")
    if not rep.ready:
        st.error(" · ".join(r.message for r in rep.blocking) + "  Fixed before it reaches the payor.")
    else:
        with st.status("📈 Approval outlook", expanded=True) as s3:
            from authops.intel.approval import Request
            am = _outlook_model()
            rq = Request(52, case.payor.payor_id, case.specialty, rng.uniform(0.3, 0.9), rng.uniform(0.6, 1.0), False,
                         0.85, case.requested_units, 1.0)
            o, recq = am.outlook(rq, case.requested_units), am.recommend(rq, 0.8)
            m1, m2 = st.columns(2)
            m1.metric("P(full approval)", f"{o['p_full']:.0%}")
            m2.metric("Recommended", f"{recq} units", f"{recq - case.requested_units:+d}", delta_color="off")
            s3.update(label=f"📈 Outlook: {o['p_full']:.0%} as requested", state="complete")
        with st.status("🔀 Routing and submitting", expanded=True) as s4:
            time.sleep(0.4)
            channel = {"portal": "browser agent", "fhir": "FHIR prior-auth API", "phone": "phone agent"}[case.payor.channel]
            decision, approved, reason = payor_decision(case, random.Random(seed))
            if decision != "denied":   # same adjudication the outlook model learned from
                from authops.intel.approval import adjudicate
                decision, approved = adjudicate(rq, case.requested_units)
            st.markdown(f"Channel: **{channel}** &nbsp;→&nbsp; payor decision: **{decision}**"
                        + (f" ({approved} units)" if approved else "") + (f" · {reason}" if reason else ""))
            s4.update(label=f"🔀 {channel}: {decision}", state="complete" if decision != "denied" else "error")
        if decision == "partial":
            st.warning(f"Partially approved: {approved} of {case.requested_units} units. The outlook would have "
                       f"recommended {recq}.")
        if decision != "denied":
            from authops.monitor.panel import forecast
            f = forecast(approved, max(1.0, approved / 12), (case.end_date - case.start_date).days, 12)
            (st.success if decision == "approved" else st.info)(f"Approved. The coverage monitor starts the reauthorization "
                       f"{max(0, f['runway_days'] - f['reauth_lead_days'])} days into the authorization.")
        else:
            st.warning("Denied. An appeal packet or a corrective resubmission is prepared in Cases → Appeals.")

st.markdown("### Results")
tiles([
    (val.get("caught_before_submission", 0), f"denials caught before submission (of {val.get('payor_denials', 0)})", "int", False),
    (ag.get("verified_submit_rate", 0), "agent submissions verified on payor portals", "pct", False),
    (ex.get("precision", 0), "precision on fields the extractor fills in", "pct", False),
] + ([(c["testers"], "testers in the user study", "int", False)] if c["testers"] else []))

cards = []
if ex:
    n_fields = ex.get("n", 0)
    cards.append({"title": "Extraction precision", "kind": "ring",
                  "k": round(ex["precision"] * ex["coverage"] * n_fields), "n": round(ex["coverage"] * n_fields),
                  "note": f"{ex['silent_error'] * 100:.1f}% silent errors",
                  "method": f"{n_fields:,} fields from 160 synthetic documents (clean, scanned, faxed) scored against ground "
                            "truth. Precision counts only fields the extractor chose to fill; it abstains when unsure."})
if abl.get("overlay_guard_on"):
    on, off = abl["overlay_guard_on"], abl["overlay_guard_off"]
    cards.append({"title": "Pop-up guard ablation", "kind": "versus", "headline": f"{on['submitted']} vs {off['submitted']} of {on['n']}",
                  "left_label": "guard off", "left": off["submitted"], "right_label": "guard on", "right": on["submitted"],
                  "method": "Same 8 cases, same portals and pop-up rates, run twice with the overlay guard switched on and off. "
                            "Without it, session notices eat the clicks and runs time out."})
if abl.get("no_credential_threshold"):
    a, b = abl["no_credential_threshold"], abl["credential_threshold_2"]
    cards.append({"title": "Account lockouts", "kind": "dots", "left_label": "no failure limit", "left": a.get("lockouts", 0),
                  "right_label": "limit of 2", "right": b.get("lockouts", 0),
                  "method": "A stale credential is planted in the Summit pool. Without a consecutive-failure limit the agent "
                            "retries it into a portal lockout; with the limit, the pool disables it first and notifies ops."})
if cal:
    better = cal["auroc_learned"] > cal["auroc_heuristic"]
    cards.append({"title": "Trained confidence model", "kind": "versus",
                  "headline": f"AUROC {cal['auroc_learned']:.3f} vs {cal['auroc_heuristic']:.3f}",
                  "left_label": "heuristic AUROC x1000", "left": int(cal["auroc_heuristic"] * 1000),
                  "right_label": "learned AUROC x1000", "right": int(cal["auroc_learned"] * 1000), "good": better,
                  "method": f"Logistic calibrator trained on {cal['n_train']} fields, tested on {cal['n_test']} fields from "
                            "unseen cases. It beat the first heuristic (0.905 to 0.954), but fixing how dates are scored "
                            f"lifted the heuristic to {cal['auroc_heuristic']:.3f}, so the model no longer clearly helps. "
                            "It is kept as the slot that human corrections from the study will retrain."})
arms = {k[4:]: v for k, v in m.get("agents", {}).items() if k.startswith("arm:")}
if "claude-haiku-4-5" in arms and "playbook" in arms:
    cl, pb = arms["claude-haiku-4-5"], arms["playbook"]
    cards.append({"title": "Claude agent vs scripted playbook", "kind": "versus",
                  "headline": f"{cl['verified_submit_rate'] * 100:.0f}% vs {pb['verified_submit_rate'] * 100:.0f}% verified",
                  "left_label": "playbook p50 seconds", "left": pb["p50_duration_s"],
                  "right_label": "Claude p50 seconds", "right": cl["p50_duration_s"], "good": False,
                  "method": f"50/50 experiment over 34 portal runs. Claude Haiku 4.5 reads the plain-English playbook and the page, "
                            f"then picks tools ({cl['runs']} runs). It matched the scripted agent's outcome after two rounds of "
                            "failure analysis, at about 15x the time per run. Iteration 1 was 13 of 15."})
if val:
    cards.append({"title": "Denials prevented", "kind": "ring", "k": val.get("caught_before_submission", 0),
                  "n": val.get("payor_denials", 0) or 1, "note": f"{val.get('false_blocks', 0)} false blocks",
                  "method": "Simulated payor decisions on 80 cases. Most denial causes are known to the rules by construction, "
                            "and one payor policy change is hidden on purpose. Try to find it in Denial Shield."})
if m.get("fhir"):
    f = m["fhir"]
    cards.append({"title": "FHIR prior-auth API", "kind": "ring", "k": f["submitted"], "n": f["n"] or 1,
                  "note": "CMS-0057-F channel",
                  "method": "Cases for the payor with a FHIR Prior Authorization API are sent as a Da Vinci PAS-shaped Bundle "
                            "instead of through a browser. Payors must offer this API from January 1, 2027."})
if cards:
    proof_cards(cards)
else:
    st.warning("No metrics found. Run `python scripts/run_all.py` then `python scripts/build_app_assets.py`.")

st.markdown("### Explore")
links = [("document_lab", "Correct an AI-read letter", "📄"), ("agent_theater", "Watch the agent on a portal", "🤖"),
         ("denial_shield", "Outlook, rules and drift", "🛡️"), ("long_charts", "150-page chart check", "📚"),
         ("coverage_monitor", "Coverage monitor", "📡"), ("benefits_cost", "Benefits call + cost", "💵"),
         ("cases_api", "Appeals and API", "🗂️"), ("playbook_studio", "Self-healing playbooks", "📝")]
for row in (links[:4], links[4:]):
    for col, (pg, label, icon) in zip(st.columns(4), row):
        col.page_link(f"app/views/{pg}.py", label=label, icon=icon)
st.markdown("<p class='ao-muted' style='margin-top:2rem'>Synthetic patients, fictional payors.</p>",
            unsafe_allow_html=True)
