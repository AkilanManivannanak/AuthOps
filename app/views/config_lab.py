import json

import pandas as pd
import streamlit as st
import yaml

from app.ui import ASSETS, asset_json, log, setup, tiles
from authops.ops import prompts

setup("Config Lab", "Draft playbooks automatically, gate prompt changes, and generate the weekly report.")

tab_prompts, tab_auto, tab_report = st.tabs(["Prompt versions and the gate", "Playbooks drafted for a new portal", "Weekly ops report"])

with tab_auto:
    ac = asset_json("autoconfig.json") or {}
    s = ac.get("summary:lexicon")
    if s:
        tiles([(s["reached_confirmation"], f"of {s['walks']} sandbox walks reached a confirmation", "int", False),
               (s["hand_field_recall"], "of hand-written field mappings reproduced", "pct", False),
               (s["wrong_mappings"], "wrong field mappings", "int", s["wrong_mappings"] > 0),
               (int(s["held_out_lakeshore"].split("/")[0]), "of 3 walks on Lakeshore, the held-out portal", "int", False)])
        df = pd.DataFrame([{"Portal": r["portal"].title(), "Service": r["specialty"].replace("_", " "),
                            "Reached confirmation": "yes" if r["reached"] else "no",
                            "Matches the hand-written playbook": "-" if r["hand_recall"] is None else f"{r['hand_recall']:.0%}",
                            "Left for a person": "; ".join(r["flagged_for_person"]) or "",
                            "Where it stopped": "" if r["reached"] else r["stopped"]}
                           for r in ac["rows"] if r["mapper"] == "lexicon"])
        st.dataframe(df, hide_index=True, width="stretch")
        if "summary:claude" in ac:
            c = ac["summary:claude"]
            st.markdown(f"**Claude label mapper:** {c['reached_confirmation']}/{c['walks']} walks reached a "
                        f"confirmation, {c['hand_field_recall']:.1%} of hand mappings, {c['wrong_mappings']} wrong.")
        st.markdown("#### The drafted Lakeshore playbook")
        st.caption("Generated from one sandbox walk; the browser agent submits with it in "
                   "tests/test_e2e_portals.py::test_drafted_playbook_submits.")
        if "lexicon:lakeshore" in ac.get("drafts", {}):
            with st.expander("Show it as code"):
                st.code(yaml.safe_dump(ac["drafts"]["lexicon:lakeshore"], sort_keys=False, width=100), language="yaml")
        st.caption("The Lakeshore portal and the label lexicon share an author; the Claude mapper uses no lexicon "
                   "and is the stricter test of unfamiliar labels.")
    else:
        st.info("Run `python scripts/run_autoconfig.py` to populate this tab.")

with tab_prompts:
    vs = prompts.versions("extract")
    pick = st.radio("Version", [p.ref for p in vs], horizontal=True)
    p = next(x for x in vs if x.ref == pick)
    a, b, c = st.columns(3)
    a.metric("Status", p.status)
    b.metric("Fingerprint", p.fingerprint)
    c.metric("Model", p.model)
    st.markdown(f"**Why this version exists:** {p.changelog}")
    st.code(p.template, language=None)
    log("prompt_view", {"ref": pick})
    st.markdown("#### Gate rules")
    st.markdown("A candidate replaces production only if, on the same golden documents: overall accuracy does not "
                "fall, silent errors (confident wrong values) do not rise, and no critical field drops by more than "
                "2 points. Every backtest is logged with both fingerprints and the golden-set fingerprint, so any "
                "number traces back to the exact prompt text.")
    logp = ASSETS.parent.parent / "reports" / "prompt_backtests.jsonl"
    rows = [json.loads(x) for x in logp.read_text().splitlines() if x.strip()] if logp.exists() else []
    if rows:
        st.dataframe(pd.DataFrame([{"when": r["ts"], "candidate": r["candidate"], "base": r["base"],
                                    "accuracy": f"{r['accuracy'][0]:.3f} -> {r['accuracy'][1]:.3f}",
                                    "silent error": f"{r['silent_error'][0]:.3f} -> {r['silent_error'][1]:.3f}",
                                    "verdict": "promote" if r["promote"] else "blocked",
                                    "why": "; ".join(r["reasons"])} for r in rows]),
                     hide_index=True, width="stretch")
    else:
        st.info("No backtests logged yet. Run `python scripts/backtest_prompt.py --candidate extract@v2`.")

with tab_report:
    rp = ASSETS / "WEEKLY_OPS_REPORT.md"
    if rp.exists():
        st.markdown(rp.read_text())
        st.download_button("Download report (.md)", rp.read_text(), "weekly_ops_report.md")
    else:
        st.info("Run `python scripts/write_ops_report.py`.")
