
import pandas as pd
import streamlit as st
import yaml

from app.sandbox import browser_available, sandbox, start_agent_run
from app.ui import log, note, pill, setup
from authops.agent.policy import PLAYBOOK_DIR

setup("Playbook Studio", "Edit a portal playbook and backtest it, or simulate a portal redesign and review the repair.")

portal = st.radio("Portal", ["northwind", "keystone", "summit"], horizontal=True)
import re  # noqa: E402

md = re.sub(r"(?m)^#{1,3} ", "#### ", (PLAYBOOK_DIR / f"{portal}.md").read_text())  # keep the page's own title on top
yml = (PLAYBOOK_DIR / f"{portal}.yaml").read_text()
a, b = st.columns([1, 1.25])
with a:
    st.markdown("#### The playbook, in plain English")
    st.markdown(md)
with st.expander("Edit as code"):
    edited = st.text_area("plan", yml, height=420, label_visibility="collapsed", key=f"yml_{portal}")
    st.caption("Ideas: delete the `wait` step on Keystone, change a field label, drop the attestation on Summit. "
               "Your edits are marked on the path above.")

try:
    spec = yaml.safe_load(edited)
    assert isinstance(spec, dict) and "pages" in spec
    valid = True
except Exception as e:
    st.error(f"The plan is not valid YAML: {e}")
    valid = False

if valid:
    import hashlib  # noqa: E402

    from app.widgets.planmap import plan_map  # noqa: E402

    with b:
        st.markdown("#### The path the agent walks")
        plan_map(spec, yaml.safe_load(yml), key=f"pm_{portal}_{hashlib.md5(edited.encode()).hexdigest()[:8]}")

n = st.slider("Backtest on how many test cases", 1, 5, 2)
if st.button("Backtest this plan", type="primary", disabled=not (valid and browser_available())):
    log("backtest", {"portal": portal, "edited": edited != yml, "n": n})
    rows = []
    prog = st.progress(0.0)
    for k, case in enumerate(sandbox()["cases"][:n]):
        q, _ = start_agent_run(case, portal, {"survey_modal_rate": 0.35, "summit_503_rate": 0.0,
                                              "summit_kick_rate": 0.0}, True, 2, spec=spec, wall_clock_s=40)
        while True:
            kind, res, _ = q.get(timeout=120)
            if kind in ("done", "error"):
                break
        if kind == "error":
            rows.append({"case": case["case_id"], "status": "error", "error": str(res)[:80]})
        else:
            rows.append({"case": case["case_id"], "status": res["status"], "error": res["error_class"],
                         "steps": res["steps"], "smoothness": res["smoothness"], "note": res["note"][:80]})
        prog.progress((k + 1) / n)
    df = pd.DataFrame(rows)
    ok = (df.status == "submitted").mean()
    st.markdown(f"### {pill(f'{ok:.0%} submitted', 'ok' if ok == 1 else 'bad')}", unsafe_allow_html=True)
    st.dataframe(df.rename(columns=lambda c: c.replace("_", " ").capitalize()), hide_index=True, width="stretch")
    if edited != yml and ok < 1:
        st.info("Your edit broke something. Real AI Ops work is exactly this loop: change, backtest in a test environment, "
                "ship only what holds. Revert by switching portals and back.")
elif not browser_available():
    st.caption("Backtests need a browser on the server; see Agent Theater for recorded runs.")

# ---------------------------------------------------------------- portal release watch
st.divider()
st.markdown("### Portal release watch")
note("A daily canary walks each portal in the test environment and compares every form with the fingerprint stored "
           "when its playbook was approved. On a mismatch the changed steps are re-drafted, hand-written judgment "
           "steps are kept, and the candidate must reach a confirmation in the test environment before it is offered.")

import json  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from authops.agent.autoconfig import draft_playbook  # noqa: E402
from authops.agent.heal import canary, heal, stored_fingerprint  # noqa: E402
from authops.portals.app import CREDENTIALS, Chaos, create_app  # noqa: E402
from authops.synth.generate import generate_cases  # noqa: E402

RELEASES = {"Current release": "", "Redesigned form (relabeled, reordered, new button)": "v2",
            "Redesign plus a new required question": "v2-required"}


@st.cache_resource(show_spinner=False)
def _walk_cases():
    cs = [c.model_dump(mode="json") for c in generate_cases(30, seed=8, gap_rate=0.0)]
    f = Path(tempfile.mkdtemp()) / "cases.json"
    f.write_text(json.dumps(cs))
    return f, next(c for c in cs if c["specialty"] == "physical_therapy")


rel_label = st.radio("Northwind release in the test environment", list(RELEASES), horizontal=True)
rel = RELEASES[rel_label]
if st.button("Run canary", type="primary"):
    cf, wcase = _walk_cases()
    mk = lambda: TestClient(create_app(cf, Chaos(survey_modal_rate=0, northwind_release=rel)))  # noqa: E731
    cred = CREDENTIALS["northwind"][0]
    with st.spinner("Walking the portal"):
        d = draft_playbook(mk(), "northwind", "/northwind/login", cred, wcase)
        res = canary(stored_fingerprint("northwind") or {}, d, "northwind")
        h = heal(yaml.safe_load((PLAYBOOK_DIR / "northwind.yaml").read_text()), mk(), "northwind",
                 "/northwind/login", cred, wcase) if res.changed else None
    st.session_state.release_watch = (rel, res, h)
    log("canary", {"release": rel or "current", "changed": res.changed, "heal": h.status if h else None})

if st.session_state.get("release_watch") and st.session_state.release_watch[0] == rel:
    _, res, h = st.session_state.release_watch
    if not res.changed:
        st.success("No change: every form matches its approved fingerprint.")
    else:
        for url, ch in res.pages.items():
            c1, c2 = st.columns(2)
            c1.markdown(f"**{url}** changed")
            c1.dataframe(pd.DataFrame([{"change": "added", "field": f, "type": t} for f, t in ch["added"]] +
                                      [{"change": "removed", "field": f, "type": t} for f, t in ch["removed"]]),
                         hide_index=True, width="stretch", height=260)
            if ch["button"]:
                c1.caption(f"Forward button: '{ch['button'][0]}' -> '{ch['button'][1]}'")
            status = {"healed": ("Candidate verified in the test environment", "ok"),
                      "needs_human": ("Needs a specialist before it can be repaired", "bad")}.get(h.status, (h.status, "ok"))
            c2.markdown(pill(status[0], status[1]), unsafe_allow_html=True)
            names = {"member_id": "Member ID", "dob": "Date of birth", "last_name": "Last name",
                     "specialty": "Service type", "cpt_csv": "Procedure codes", "icd_csv": "Diagnosis codes",
                     "units": "Units", "start": "Start date", "end": "End date", "npi": "Provider NPI",
                     "files": "Documents"}
            if h.renamed:
                c2.dataframe(pd.DataFrame([{"request field": names.get(v, v), "approved label": o.capitalize(),
                                            "new label": n.capitalize()} for v, o, n in h.renamed]),
                             hide_index=True, width="stretch")
            optional = [u for u in h.added_unmapped if "optional" in u.lower()]
            required = [u for u in h.added_unmapped if u not in optional]
            if required:
                c2.warning("Needs a specialist before approval: " + "; ".join(required))
            if optional:
                c2.caption("New optional fields left blank: " + "; ".join(optional))
            if h.carried_over:
                c2.caption("Kept from the approved playbook: " + "; ".join(h.carried_over))
            if h.stopped:
                c2.caption(f"Test walk stopped: {h.stopped}")
        with st.expander("Patch for review"):
            st.code(h.patch or "(no candidate)", language="diff")
        if h.status == "healed":
            b1, b2 = st.columns(2)
            if b1.button("Approve candidate"):
                st.session_state.approved_heal = h.candidate
                log("heal_approve", {"release": rel})
                st.success("Approved as the next Northwind playbook version (kept in this session).")
            if browser_available() and b2.button("Backtest candidate in the browser"):
                q, _ = start_agent_run(sandbox()["cases"][0], "northwind",
                                       {"survey_modal_rate": 0.35, "northwind_release": rel}, True, 2,
                                       spec=h.candidate, wall_clock_s=40)
                while True:
                    kind, r, _ = q.get(timeout=120)
                    if kind in ("done", "error"):
                        break
                st.write(r if kind == "error" else {k: r[k] for k in ("status", "steps", "smoothness", "note")})
