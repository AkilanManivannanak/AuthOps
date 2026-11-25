import streamlit as st

from app.ui import asset_json, run_view, setup

setup("How it works" if __import__("app.account", fromlist=["role"]).role() == "patient" else "How it was measured", "Four numbers, each one tap away from the page that reproduces it, then the method "
      "and what it does not prove.")


@st.cache_data(show_spinner="Scoring the approval outlook on held-out weeks")
def _approval():
    saved = asset_json("approval_eval.json")   # written by scripts/build_app_assets.py, same file the README quotes
    if saved:
        return {p["policy"]: p["first_pass_full"] for p in saved["policies"]}
    from authops.intel.approval import evaluate
    return {p["policy"]: p["first_pass_full"] for p in evaluate(target=0.8)["policies"]}


m = asset_json("metrics.json") or {}
cr = asset_json("care_readiness.json") or {}
ex = m.get("extraction", {}).get("arms", {}).get("rules", {}).get("summary", {})
ap = _approval()
mon, bv = cr.get("monitor", {}), cr.get("benefits", {})
cards = []
if ex:
    cards.append((f"{ex['all']['accuracy']:.1%}", "of document fields read right",
                  f"{ex['all']['n']:,} fields on clean, scanned and faxed letters and plans; {ex['cond:fax']['accuracy']:.1%} "
                  f"on faxes alone. When unsure it leaves the field for a person: {ex['all']['silent_error']:.1%} are filled in wrong.",
                  "app/views/prior_authorizations.py", {"tool": "Read a document"}, "Read a document yourself"))
if ap:
    cards.append((f"{ap['model, target P(full) >= 80%']:.1%}", "approved in full on the first pass",
                  f"Asking for the amount the outlook recommends, on 12 held-out weeks of payor decisions. Asking for the "
                  f"full clinical need: {ap['ask for clinical need']:.1%}.",
                  "app/views/prior_authorizations.py", {"tool": "Check a request"}, "Try the outlook"))
if mon:
    cut = mon["proactive"]["denied_dollars_cut_vs_reactive"]
    cards.append((f"{cut[1]:.0%}", "fewer denied dollars than reacting",
                  f"Weekly eligibility checks and a burn-down forecast, against learning from denials. 200 patients, 26 "
                  f"weeks, 5 seeds (range {cut[0]:.0%} to {cut[2]:.0%}).",
                  "app/views/insurance_monitoring.py", None, "See the runway"))
if bv:
    cards.append((f"{bv['careful_readback']['field_accuracy']:.1%}", "of benefit-call fields right",
                  f"Careful parsing plus reading every number back, on 120 calls with speech errors. The first number heard: "
                  f"{bv['naive']['field_accuracy']:.1%}.", "app/views/benefit_checks.py", None, "Listen to a call"))

cols = st.columns(len(cards) or 1)
for col, (num, lab, how, page, qp, link) in zip(cols, cards):
    col.markdown(f"<div class='ao-card' style='min-height:250px'><div class='ao-fig' style='color:#5B2A86'>{num}</div>"
                 f"<div style='font-weight:600;margin:8px 0 6px'>{lab}</div><div class='ao-muted'>{how}</div></div>",
                 unsafe_allow_html=True)
    try:
        col.page_link(page, label=link, icon=":material/arrow_forward:", query_params=qp)
    except Exception:   # the page is not in this person's menu
        pass

st.markdown("### Method")
run_view("app/views/method.py")
st.markdown("**API.** The same pipeline is exposed as a small REST API (`authops/api/app.py`): create an "
            "authorization, post payor events, and receive signed webhooks. Run it with "
            "`uvicorn authops.api.app:app --port 8100` and open `/docs`.")
