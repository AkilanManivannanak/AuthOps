"""Write the weekly AI Operations report from the latest run artifacts.

    python scripts/write_ops_report.py      -> reports/WEEKLY_OPS_REPORT.md (+ app copy)

Deterministic: every sentence is filled from metrics, so the report can be regenerated after
any run and diffed week over week. It is written for an ops lead who has two minutes: what
changed, what is safe to automate further, what needs a decision, and who acts next.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
A = ROOT / "app" / "assets"
sys.path.insert(0, str(ROOT))


def j(name: str) -> dict:
    p = A / name
    return json.loads(p.read_text()) if p.exists() else {}


def pct(x, d=1) -> str:
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def main() -> None:
    m, cr, ac = j("metrics.json"), j("care_readiness.json"), j("autoconfig.json")
    log = ROOT / "reports" / "prompt_backtests.jsonl"
    backtests = [json.loads(x) for x in log.read_text().splitlines() if x.strip()] if log.exists() else []
    ag, val, ramp = m.get("agents", {}), m.get("validation", {}), m.get("qa_ramp", {})
    ex = m.get("extraction", {}).get("arms", {}).get("rules", {}).get("summary", {}).get("all", {})
    L = [f"# AI Operations weekly report", f"_Generated {time.strftime('%Y-%m-%d')} from run artifacts. Synthetic "
         "patients and sandbox portals only._", ""]

    # 1. headline
    allr = ag.get("all", {})
    L += ["## Headline", ""]
    L.append(f"- **Submissions:** {allr.get('runs', 0)} agent runs, {pct(allr.get('verified_submit_rate'))} verified "
             f"against the payor confirmation, mean smoothness {allr.get('mean_smoothness', 0)}/100, "
             f"{ag.get('silent_errors', 0)} silent errors found in QA.")
    if val:
        L.append(f"- **Denials prevented:** {val['caught_before_submission']} of {val['payor_denials']} predictable "
                 f"denials caught before submission, {val['false_blocks']} clean requests blocked by mistake.")
    if ex:
        L.append(f"- **Document extraction:** {pct(ex.get('precision'))} precision on fields filled, "
                 f"{pct(ex.get('silent_error'))} silent error, {pct(ex.get('doc_ok'))} of documents with every "
                 "critical field right.")
    da = cr.get("docagent", {})
    if "claude_agent" in da:
        a, o = da["claude_agent"]["summary"], da["claude_oneshot"]["summary"]
        L.append(f"- **Long charts:** the background document agent made {a['all']['false_pass']} false passes vs "
                 f"{o['all']['false_pass']} for a single call, and held {pct(a['100+ pages']['accuracy'])} on 100+ page "
                 f"charts vs {pct(o['100+ pages']['accuracy'])}.")
    L.append("")

    # 2. rollout
    L += ["## Portal rollout status", "", "| Portal | Runs | Verified | Smoothness | Human QA share | Decision |",
          "|---|---|---|---|---|---|"]
    for portal, r in ramp.items():
        a = ag.get(f"portal:{portal}", {})
        share = r["final_qa_share"]
        decision = ("hold QA at 100%" if a.get("verified_submit_rate", 0) < 0.95 else
                    "lower QA share next week if metrics hold" if share > 0.2 else "keep sampling at floor")
        L.append(f"| {portal} | {a.get('runs', 0)} | {pct(a.get('verified_submit_rate'))} | {a.get('mean_smoothness', 0)} "
                 f"| {share:.0%} | {decision} |")
    L.append("")

    # 3. new portals
    s = ac.get("summary:lexicon")
    if s:
        L += ["## New portal configuration", ""]
        L.append(f"- Auto-drafted playbooks reached a confirmation on {s['reached_confirmation']} of {s['walks']} sandbox "
                 f"walks, including {s['held_out_lakeshore']} on the held-out Lakeshore portal. Drafts reproduced "
                 f"{pct(s['hand_field_recall'])} of hand-written field mappings with {s['wrong_mappings']} wrong mappings.")
        flagged = {}
        for r in ac.get("rows", []):
            for f in r["flagged_for_person"]:
                flagged.setdefault(r["portal"], set()).add(f)
        for portal, fs in flagged.items():
            L.append(f"- **Needs a specialist decision ({portal}):** " + "; ".join(sorted(fs)) + ".")
        L.append("")

    # 3b. payor policy changes and portal releases
    from authops.intel.drift import detect, simulate_stream
    alerts = detect(simulate_stream(seed=4))
    if alerts:
        L += ["## Payor policy changes detected", "", "| Week | Payor | Specialty | Signal | Before | After | Proposed |",
              "|---|---|---|---|---|---|---|"]
        for a in alerts:
            prop = json.dumps(a.proposal.get("specialties", {}))[:70]
            L.append(f"| {a.week_detected} | {a.payor} | {a.specialty.replace('_', ' ')} | {a.signal[:55]} | "
                     f"{a.rate_before} | {a.rate_after} | `{prop}` |")
        L.append("")
    can = ROOT / "reports" / "canary.json"
    if can.exists():
        c = json.loads(can.read_text())
        L += ["## Portal releases", ""]
        for portal, r in c["portals"].items():
            if r.get("changed"):
                hh = r.get("heal", {})
                L.append(f"- **{portal}** changed (simulated release {c['release']}): heal {hh.get('status', 'n/a')}, "
                         f"{len(hh.get('renamed', []))} fields re-mapped, verified in sandbox: {hh.get('verified_in_sandbox')}"
                         + (f"; needs a decision on {', '.join(hh['needs_human'])}" if hh.get("needs_human") else "") + ".")
            else:
                L.append(f"- {portal}: unchanged.")
        L.append("")

    # 4. what to fix next (ranked)
    L += ["## Top issues and owners", ""]
    issues = []
    ev = m.get("portal_events", {})
    if ev.get("lockout"):
        issues.append((3, f"Summit locked a credential {ev['lockout']} {'time' if ev['lockout'] == 1 else 'times'}; the pool disabled the stale one. "
                          "Owner: ops, rotate the password with the payor."))
    if ex and ex.get("doc_ok", 1) < 0.8:
        worst = sorted(((k[6:], v["accuracy"]) for k, v in m["extraction"]["arms"]["rules"]["summary"].items()
                        if k.startswith("field:")), key=lambda x: x[1])[:3]
        issues.append((2, "Extraction: only " + pct(ex["doc_ok"]) + " of documents are fully right. Weakest fields: " +
                       ", ".join(f"{f} ({pct(a)})" for f, a in worst) + ". Owner: AI Ops, prompt backtest extract@v2."))
    bv = cr.get("benefits", {})
    if bv:
        issues.append((1, f"Benefits calls: read-back cuts wrong fields from {bv['careful']['fluent_wrong_fields']} to "
                          f"{bv['careful_readback']['fluent_wrong_fields']} per 120 calls; ship read-back to every phone "
                          "workflow. Owner: AI Ops + phone engineering."))
    mon = cr.get("monitor", {})
    if mon:
        issues.append((1, f"Coverage monitor: proactive checks cut denied revenue "
                          f"{pct(mon['proactive']['denied_dollars_cut_vs_reactive'][1], 0)} vs reacting to denials in "
                          "simulation; pilot weekly checks with one ABA customer. Owner: customer success."))
    for i, (_, text) in enumerate(sorted(issues, key=lambda x: -x[0]), 1):
        L.append(f"{i}. {text}")
    L.append("")

    # 5. prompt changes
    L += ["## Prompt changes", ""]
    if backtests:
        for b in backtests[-3:]:
            L.append(f"- {b['ts']}: {b['candidate']} ({b['candidate_fp']}) vs {b['base']} on golden set {b['dataset']}: "
                     f"accuracy {b['accuracy'][0]:.3f} -> {b['accuracy'][1]:.3f}, silent error {b['silent_error'][0]:.3f} -> "
                     f"{b['silent_error'][1]:.3f}. **{'Promote' if b['promote'] else 'Blocked'}**"
                     + (": " + "; ".join(b["reasons"]) if b["reasons"] else "") + ".")
    else:
        L.append("- No backtests this week. Candidate extract@v2 is waiting for a backtest against production extract@v1.")
    L.append("")
    L += ["## Decisions needed", "",
          "- Approve the next QA-share step for portals whose metrics held all week.",
          "- Assign a specialist to answer the flagged clinical questions on Summit and the ABA school fields on Keystone "
          "so their drafts can be completed.", ""]
    out = ROOT / "reports" / "WEEKLY_OPS_REPORT.md"
    out.write_text("\n".join(L))
    shutil.copy(out, A / "WEEKLY_OPS_REPORT.md")
    print(out.read_text())


if __name__ == "__main__":
    main()
