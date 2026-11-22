import streamlit as st

from app.ui import FOREST, RED, asset_json, proof_cards, setup, store, tiles

setup("Prior auths, cleared before care starts",
      "AuthOps reads the paperwork, catches the denials it can predict, submits through whichever "
      "channel the payor offers, and earns the right to skip human review one portal at a time.")

m = asset_json("metrics.json") or {}
ex = (m.get("extraction", {}).get("arms", {}).get("rules", {}) or {}).get("summary", {}).get("all", {})
val = m.get("validation", {})
ag = m.get("agents", {}).get("all", {})
abl = m.get("ablations", {})
cal = m.get("calibration", {})
c = store().counts()

tiles([
    (val.get("caught_before_submission", 0), f"denials caught before submission (of {val.get('payor_denials', 0)})", "int", False),
    (ag.get("verified_submit_rate", 0), "agent submissions verified on payor portals", "pct", False),
    (ex.get("precision", 0), "precision on fields the extractor fills in", "pct", False),
] + ([(c["testers"], "testers in the user study", "int", False)] if c["testers"] else []))

st.markdown("### How a request moves")
steps = [("📄", "Read", "OCR + extraction with per-field confidence; unsure fields abstain"),
         ("🛡️", "Check", "Payor rules flag the gaps that cause denials"),
         ("🔀", "Route", "FHIR API if the payor has one, else portal agent, else phone"),
         ("🤖", "Submit", "Browser agent with guards, retries and a 50-turn cap"),
         ("✅", "Verify", "Confirmation must match patient, member and codes"),
         ("📈", "Earn autonomy", "Human QA share drops only while metrics hold"),
         ("📡", "Stay current", "Payor rule changes and portal releases detected and repaired")]
cells = "".join(f"<div class='ao-tile'><div style='font-size:1.8rem'>{icon}</div><b>{name}</b>"
                f"<div class='ao-muted'>{desc}</div></div>" for icon, name, desc in steps)
st.markdown(f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px'>{cells}</div>",
            unsafe_allow_html=True)

st.markdown("### Care readiness: what happens between visits")
cr = asset_json("care_readiness.json") or {}
if cr:
    mon, bv = cr["monitor"]["proactive"], cr["benefits"]
    l1, l2, l3, l4 = st.columns(4)
    l1.page_link("app/views/long_charts.py", label="Long-chart validation: 12 to 150 page charts", icon="📚")
    l2.page_link("app/views/coverage_monitor.py",
                 label=f"Coverage Monitor: {mon['denied_dollars_cut_vs_reactive'][1]:.0%} less denied revenue", icon="📡")
    l3.page_link("app/views/benefits_cost.py",
                 label=f"Benefits calls: {bv['careful_readback']['field_accuracy']:.1%} fields right", icon="💵")
    l4.page_link("app/views/cases_api.py", label="Cases and API: SLA clocks, webhooks", icon="🗂️")

st.markdown("### Results")
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

st.markdown("### Try it")
a, b, c2, d = st.columns(4)
a.page_link("app/views/document_lab.py", label="Correct an AI-read letter", icon="📄")
b.page_link("app/views/agent_theater.py", label="Watch an agent fight a portal", icon="🤖")
c2.page_link("app/views/denial_shield.py", label="Find the hidden payor rule", icon="🛡️")
d.page_link("app/views/join.py", label="Join the tester study", icon="🙋")
st.markdown(f"<p class='ao-muted' style='margin-top:2rem'>Synthetic data, fictional payors. Built to mirror how prior-auth "
            f"AI operations teams work. <span style='color:{FOREST}'>Green</span> means earned, "
            f"<span style='color:{RED}'>red</span> means at risk.</p>", unsafe_allow_html=True)
