"""End-to-end run: data -> extraction eval -> validation -> routing -> agents -> QA -> report.

Usage:
    python scripts/run_all.py                 # offline (rules + playbook policy)
    python scripts/run_all.py --cases 60      # bigger run
    ANTHROPIC_API_KEY=... python scripts/run_all.py --llm   # adds Claude arms

Writes reports/REPORT.md, reports/metrics.json, reports/error_dataset.csv and
reports/authops.db (every run and step, queryable with SQL).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics as stats
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from authops.agent.credentials import CredentialPool  # noqa: E402
from authops.agent.policy import ClaudePolicy, PlaybookPolicy  # noqa: E402
from authops.agent.runtime import AgentRuntime  # noqa: E402
from authops.channels.router import choose_channel, submit_fhir  # noqa: E402
from authops.docintel.evaluate import score  # noqa: E402
from authops.docintel.extract import ClaudeExtractor, RuleExtractor, classify_doc  # noqa: E402
from authops.docintel.ocr import ocr_pages  # noqa: E402
from authops.llm import ClaudeLLM, UsageMeter, llm_available  # noqa: E402
from authops.ops.experiments import Arm, Experiment, QARamp  # noqa: E402
from authops.ops.qa import review  # noqa: E402
from authops.ops.store import Store  # noqa: E402
from authops.phone.ivr import run_call  # noqa: E402
from authops.portals.app import CREDENTIALS, Chaos  # noqa: E402
from authops.portals.server import PortalServer  # noqa: E402
from authops.schemas import DocType  # noqa: E402
from authops.synth.generate import generate_cases  # noqa: E402
from authops.synth.render import render_corpus  # noqa: E402
from authops.validation.rules import load_requirements, validate_case  # noqa: E402

TODAY = date(2026, 11, 17)


def launch_browser(p):
    exe = os.environ.get("AUTHOPS_CHROME")
    if not exe and Path("/usr/bin/google-chrome").exists() and not any(
            Path.home().glob(".cache/ms-playwright/chromium-*")):
        exe = "/usr/bin/google-chrome"
    kw = {"headless": os.environ.get("AUTHOPS_HEADED") != "1", "args": ["--no-sandbox"]}
    if exe:
        kw["executable_path"] = exe
    return p.chromium.launch(**kw)


def pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=80)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--llm", action="store_true", help="add Claude arms (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--skip-agents", action="store_true")
    args = ap.parse_args()
    use_llm = args.llm and llm_available()
    if args.llm and not use_llm:
        print("ANTHROPIC_API_KEY not set: running offline arms only")

    data = ROOT / "data"
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    db_path = reports / "authops.db"
    if db_path.exists():
        db_path.unlink()
    store = Store(db_path)
    import platform

    import pytesseract
    metrics: dict = {"generated": time.strftime("%Y-%m-%d %H:%M"), "llm": use_llm, "cases": args.cases,
                     "env": {"tesseract": str(pytesseract.get_tesseract_version()),
                             "python": platform.python_version(), "os": platform.system()}}
    meter = UsageMeter()

    # 1. data -----------------------------------------------------------------
    t = time.time()
    cases = generate_cases(args.cases, seed=args.seed, today=TODAY, gap_rate=0.3)
    manifest = render_corpus(cases, data)
    print(f"[1/6] rendered {len(manifest)} documents for {len(cases)} cases in {time.time() - t:.0f}s")

    # 2. document intelligence -------------------------------------------------
    t = time.time()
    ocr_cache, cls_ok = {}, 0
    for d in manifest:
        ocr_cache[d["doc_id"]] = ocr_pages(d["pages"])
        cls_ok += classify_doc(ocr_cache[d["doc_id"]].text).value == d["doc_type"]
    extractors = [RuleExtractor()]
    if use_llm:
        extractors.append(ClaudeExtractor(ClaudeLLM("claude-haiku-4-5", meter)))
    extraction = {"classification_accuracy": round(cls_ok / len(manifest), 3), "arms": {}}
    arm_rows: dict[str, list[dict]] = {}
    for ex in extractors:
        outs = [ex.extract(d["doc_id"], ocr_cache[d["doc_id"]], DocType(d["doc_type"]), d["pages"])
                for d in manifest]
        s = score(outs, manifest)
        arm_rows[ex.name] = s["rows"]
        lat = [o.latency_ms for o in outs]
        extraction["arms"][ex.name] = {
            "summary": s["summary"], "p50_latency_ms": round(stats.median(lat)),
            "tokens_in": sum(o.tokens_in for o in outs), "tokens_out": sum(o.tokens_out for o in outs)}
        with open(reports / f"extraction_errors_{ex.name.replace(':', '_')}.csv", "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(s["rows"][0].keys()))
            w.writeheader()
            w.writerows(r for r in s["rows"] if not r["ok"])
    metrics["extraction"] = extraction

    # 2b. trained confidence calibration (rules arm) ---------------------------
    from authops.docintel.calibrate import risk_coverage_curve, save_model, train_and_evaluate

    rules_outs = [RuleExtractor().extract(d["doc_id"], ocr_cache[d["doc_id"]], DocType(d["doc_type"]))
                  for d in manifest]
    rows = score(rules_outs, manifest)["rows"]
    doc_meta = {d["doc_id"]: {"template": d["template"], "ocr_mean_conf": o.ocr_mean_conf or 0.0}
                for d, o in zip(manifest, rules_outs)}
    model, cal, held = train_and_evaluate(rows, doc_meta)
    save_model(model, reports / "calibrator.json")
    (reports / "risk_coverage.json").write_text(json.dumps({
        "heuristic": risk_coverage_curve(held["heuristic"], held["labels"]),
        "learned": risk_coverage_curve(held["learned"], held["labels"])}, indent=1))
    (reports / "extraction_rows.json").write_text(json.dumps(
        [dict(r, template=doc_meta[r["doc_id"]]["template"]) for r in rows], default=str))
    metrics["calibration"] = cal.as_dict()
    print(f"[2/6] OCR + extraction on {len(manifest)} docs in {time.time() - t:.0f}s")

    # 3. pre-submission validation ---------------------------------------------
    req = load_requirements()
    decisions = {d["case_id"]: d["truth"]["decision"] for d in manifest if d["doc_type"] != "treatment_plan"}
    tp = fp = fn = tn = 0
    misses, rule_hits = [], Counter()
    reports_by_case = {}
    for c in cases:
        rep = validate_case(c, TODAY, req, llm=ClaudeLLM("claude-haiku-4-5", meter) if use_llm else None,
                            documents_text=ocr_cache[f"{c.case_id}_treatment_plan"].text,
                            include_custom=use_llm)
        reports_by_case[c.case_id] = rep
        flagged = not rep.ready
        denied = decisions[c.case_id] == "denied"
        for r in rep.blocking:
            rule_hits[r.rule] += 1
        if flagged and denied:
            tp += 1
        elif flagged and not denied:
            fp += 1
        elif denied:
            fn += 1
            misses.append({"case_id": c.case_id, "payor": c.payor.payor_id, "specialty": c.specialty,
                           "units": c.requested_units})
        else:
            tn += 1
    metrics["validation"] = {
        "cases": len(cases), "payor_denials": tp + fn, "caught_before_submission": tp,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "false_blocks": fp, "missed": misses, "rule_hits": dict(rule_hits)}
    print(f"[3/6] validation caught {tp}/{tp + fn} payor denials before submission")

    if args.skip_agents:
        (reports / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
        return

    # 4. routing + agents ------------------------------------------------------
    from playwright.sync_api import sync_playwright

    ready = [c for c in cases if reports_by_case[c.case_id].ready]
    by_channel = defaultdict(list)
    for c in ready:
        by_channel[choose_channel(c.model_dump(mode="json"), req)].append(c)
    arms = [Arm("playbook", lambda portal: PlaybookPolicy(portal), 1.0)]
    if use_llm:
        arms = [Arm("playbook", lambda portal: PlaybookPolicy(portal), 0.5),
                Arm("claude-haiku-4-5", lambda portal: ClaudePolicy(portal, ClaudeLLM("claude-haiku-4-5", meter)), 0.5)]
    exp = Experiment("portal-policy-v1", arms)
    ramp = QARamp(window=6)
    disabled_events = []
    pool = CredentialPool(CREDENTIALS, threshold=2,
                          on_disable=lambda c, why: disabled_events.append((c.username, why)))
    runs, qa_rows = [], []
    t = time.time()
    with PortalServer(data / "cases.json", Chaos()) as srv, sync_playwright() as p:
        browser = launch_browser(p)
        rt = AgentRuntime(browser, srv.url, pool, store)
        for c in by_channel["portal"]:
            cd = c.model_dump(mode="json")
            portal = c.payor.portal_id
            arm = exp.assign(c.case_id)
            qa_routed = ramp.route_to_qa(portal)
            files = [str(data / "docs" / f"{c.case_id}_treatment_plan.pdf")]
            n_before = len(srv.state.submissions)
            r = rt.run(cd, portal, arm.make_policy(portal), files, arm=arm.name, qa_routed=qa_routed)
            subs = srv.state.submissions[n_before:]
            issues = review(subs[-1], cd) if subs else []
            for i in issues:
                store.qa(r.run_id, c.case_id, i["field"], i["submitted"], i["expected"], i["severity"], i["comment"])
                qa_rows.append({"run_id": r.run_id, "case_id": c.case_id, "portal": portal, "arm": arm.name, **i})
            major = any(i["severity"] == "major" for i in issues)
            silent = major and not qa_routed and r.status == "submitted"
            ramp.record(portal, r.status == "submitted" and not major, r.smoothness, silent)
            runs.append({"case_id": c.case_id, "portal": portal, "arm": arm.name, "qa_routed": qa_routed,
                         "status": r.status, "error_class": r.error_class, "steps": r.steps,
                         "smoothness": r.smoothness, "duration_s": r.duration_s, "verified": r.verified,
                         "major_issues": major, "silent_error": silent, "counts": r.counts,
                         "tokens_in": r.tokens_in, "tokens_out": r.tokens_out})
            print(f"   {portal:9s} {c.case_id} {arm.name:16s} {r.status:11s} {r.error_class:16s} "
                  f"steps={r.steps:2d} smooth={r.smoothness:5.1f} {r.duration_s:5.1f}s")
        # FHIR channel (CMS-0057-F direction)
        fhir = [dict(submit_fhir(srv.url, c.model_dump(mode="json")), case_id=c.case_id)
                for c in by_channel["fhir"]]
        # Ablations on fresh state ------------------------------------------------
        ablations = {}
        sample = [c for c in cases if c.payor.portal_id in ("northwind", "keystone")][:8]
        for name, guard in (("overlay_guard_on", True), ("overlay_guard_off", False)):
            art = AgentRuntime(browser, srv.url, CredentialPool(CREDENTIALS), store, overlay_guard=guard,
                               wall_clock_s=30)
            res = [art.run(c.model_dump(mode="json"), c.payor.portal_id, PlaybookPolicy(c.payor.portal_id),
                           [str(data / "docs" / f"{c.case_id}_treatment_plan.pdf")], arm=name) for c in sample]
            ablations[name] = {"n": len(res), "submitted": sum(r.status == "submitted" for r in res),
                               "errors": dict(Counter(r.error_class for r in res if r.error_class))}
        srv.state.summit_locked.clear()
        summit_cases = [c for c in cases if not c.injected_gaps][:9]
        for name, thr in (("credential_threshold_2", 2), ("no_credential_threshold", 99)):
            srv.state.summit_locked.clear()
            srv.state.summit_fail.clear()
            pool2 = CredentialPool(CREDENTIALS, threshold=thr)
            art = AgentRuntime(browser, srv.url, pool2, store)
            locks_before = sum(1 for e in srv.state.events if e[0] == "lockout")
            res = [art.run(c.model_dump(mode="json"), "summit", PlaybookPolicy("summit"),
                           [str(data / "docs" / f"{c.case_id}_treatment_plan.pdf")], arm=name)
                   for c in summit_cases]
            ablations[name] = {"n": len(res), "submitted": sum(r.status == "submitted" for r in res),
                               "lockouts": sum(1 for e in srv.state.events if e[0] == "lockout") - locks_before,
                               "errors": dict(Counter(r.error_class for r in res if r.error_class))}
        portal_events = Counter(e[0] for e in srv.state.events)
        browser.close()
    print(f"[4/6] {len(runs)} portal runs + {len(fhir)} FHIR submissions + ablations in {time.time() - t:.0f}s")

    # 5. phone channel ---------------------------------------------------------
    records = {c.patient.member_id: {"dob": c.patient.dob.isoformat(), "status": "approved",
                                     "ref": str(40000000 + i), "copay": 25} for i, c in enumerate(cases)}
    calls = [run_call(c.model_dump(mode="json"), purpose, records, seed=i)
             for i, c in enumerate(by_channel["phone"]) for purpose in ("benefits", "status")]
    metrics["phone"] = {"calls": len(calls), "completed": sum(c.status == "completed" for c in calls),
                        "mean_turns": round(stats.mean(c.turns for c in calls), 1) if calls else None,
                        "member_id_repeats": sum(sum("repeat the member" in e.text for e in c.events) for c in calls)}
    print(f"[5/6] {len(calls)} phone calls")

    # 6. report ------------------------------------------------------------------
    agg = defaultdict(lambda: defaultdict(list))
    for r in runs:
        for key in (f"portal:{r['portal']}", f"arm:{r['arm']}", "all"):
            agg[key]["ok"].append(r["status"] == "submitted" and r["verified"])
            agg[key]["smooth"].append(r["smoothness"])
            agg[key]["dur"].append(r["duration_s"])
            agg[key]["steps"].append(r["steps"])
            agg[key]["major"].append(r["major_issues"])
    metrics["agents"] = {k: {"runs": len(v["ok"]), "verified_submit_rate": round(sum(v["ok"]) / len(v["ok"]), 3),
                             "mean_smoothness": round(stats.mean(v["smooth"]), 1),
                             "p50_duration_s": round(stats.median(v["dur"]), 2),
                             "mean_steps": round(stats.mean(v["steps"]), 1),
                             "runs_with_major_qa_issue": sum(v["major"])} for k, v in agg.items()}
    metrics["agents"]["error_classes"] = dict(Counter(r["error_class"] for r in runs if r["error_class"]))
    metrics["agents"]["silent_errors"] = sum(r["silent_error"] for r in runs)
    metrics["qa_ramp"] = {p: {"final_qa_share": s.qa_share, "log": s.log} for p, s in ramp.state.items()}
    metrics["credentials"] = {"disabled": disabled_events, "pool": pool.status()}
    metrics["portal_events"] = dict(portal_events)
    metrics["fhir"] = {"submitted": sum(f["status"] == "submitted" for f in fhir), "n": len(fhir),
                       "p50_s": round(stats.median([f["duration_s"] for f in fhir]), 3) if fhir else None}
    metrics["ablations"] = ablations
    metrics["stats"] = rollout_stats(metrics, arm_rows)
    metrics["llm_usage"] = {"calls": meter.calls, "tokens_in": meter.tokens_in, "tokens_out": meter.tokens_out,
                            "cost_usd": round(meter.cost_usd, 4)}
    metrics["routing"] = {k: len(v) for k, v in by_channel.items()}
    metrics["held_for_fixes"] = len(cases) - len(ready)
    (reports / "metrics.json").write_text(json.dumps(metrics, indent=1, default=str))
    with open(reports / "agent_runs.json", "w") as fh:
        json.dump(runs, fh, indent=1)
    with open(reports / "error_dataset.csv", "w", newline="") as fh:  # always rewrite: no stale rows
        w = csv.DictWriter(fh, fieldnames=["run_id", "case_id", "portal", "arm", "field", "submitted",
                                           "expected", "severity", "comment"])
        w.writeheader()
        w.writerows(qa_rows)
    write_report(metrics, reports / "REPORT.md")
    print(f"[6/6] wrote {reports / 'REPORT.md'}")


def rollout_stats(m: dict, arm_rows: dict) -> dict:
    """Intervals and significance for every comparison the report makes."""
    from authops.ops.stats import bootstrap_diff, fisher_exact, mcnemar_exact, wilson

    out: dict = {"extraction": {}, "ablations": {}}
    for arm, rows in arm_rows.items():
        k = sum(r["ok"] for r in rows)
        docs: dict[str, bool] = {}
        for r in rows:
            docs[r["doc_id"]] = docs.get(r["doc_id"], True) and r["ok"]
        silent = sum((not r["ok"]) and not r["abstained"] for r in rows)
        out["extraction"][arm] = {
            "field_acc_ci": [round(x, 3) for x in wilson(k, len(rows))],
            "doc_ok_ci": [round(x, 3) for x in wilson(sum(docs.values()), len(docs))],
            "silent_error_ci": [round(x, 4) for x in wilson(silent, len(rows))]}
    if len(arm_rows) >= 2:
        (a, ra), (b, rb) = list(arm_rows.items())[:2]
        key = {(r["doc_id"], r["field"]): r["ok"] for r in rb}
        pairs = [(r["ok"], key[(r["doc_id"], r["field"])], r["doc_id"]) for r in ra
                 if (r["doc_id"], r["field"]) in key]
        d, lo, hi = bootstrap_diff([float(x) for x, _, _ in pairs], [float(y) for _, y, _ in pairs],
                                   groups=[g for _, _, g in pairs])
        out["extraction"]["paired"] = {
            "arms": [a, b], "acc_diff": round(d, 4), "ci_doc_bootstrap": [round(lo, 4), round(hi, 4)],
            "only_a": sum(x and not y for x, y, _ in pairs), "only_b": sum(y and not x for x, y, _ in pairs),
            "mcnemar_p": round(mcnemar_exact(sum(x and not y for x, y, _ in pairs),
                                             sum(y and not x for x, y, _ in pairs)), 4)}
    ab = m.get("ablations", {})
    for on, off, what in (("overlay_guard_on", "overlay_guard_off", "submitted"),
                          ("credential_threshold_2", "no_credential_threshold", "submitted")):
        if on in ab and off in ab:
            a1, n1, a2, n2 = ab[on][what], ab[on]["n"], ab[off][what], ab[off]["n"]
            out["ablations"][on] = {"on": f"{a1}/{n1}", "off": f"{a2}/{n2}",
                                    "fisher_p": round(fisher_exact(a1, n1 - a1, a2, n2 - a2), 4)}
    v = m.get("validation", {})
    if v.get("payor_denials"):
        out["validation_recall_ci"] = [round(x, 3) for x in wilson(v["caught_before_submission"],
                                                                   v["payor_denials"])]
    return out


def write_report(m: dict, path: Path) -> None:
    L = ["# AuthOps evaluation report", "",
         f"Generated {m['generated']}. {m['cases']} synthetic cases, fictional payors, no real PHI. "
         f"LLM arms: {'on' if m['llm'] else 'off (offline run)'}. "
         f"Environment: Tesseract {m['env']['tesseract']}, Python {m['env']['python']}, {m['env']['os']}.", ""]
    ex = m["extraction"]
    L += ["## 1. Document extraction", "",
          f"Document type classification accuracy: {pct(ex['classification_accuracy'])}", "",
          "| Extractor | Field accuracy | Precision when answered | Coverage | Silent error | Docs fully correct | p50 latency |",
          "|---|---|---|---|---|---|---|"]
    for name, a in ex["arms"].items():
        s = a["summary"]["all"]
        L.append(f"| {name} | {pct(s['accuracy'])} | {pct(s['precision'])} | {pct(s['coverage'])} | "
                 f"{pct(s['silent_error'])} | {pct(s.get('doc_ok'))} | {a['p50_latency_ms']} ms |")
    L += ["", "By image condition and template (first extractor):", "",
          "| Slice | n fields | Accuracy | Precision | Coverage | Silent error |", "|---|---|---|---|---|---|"]
    first = next(iter(ex["arms"].values()))["summary"]
    for k in sorted(first):
        if k.startswith(("cond:", "tmpl:", "type:")):
            s = first[k]
            L.append(f"| {k} | {s['n']} | {pct(s['accuracy'])} | {pct(s['precision'])} | {pct(s['coverage'])} | {pct(s['silent_error'])} |")
    L += ["", "Weakest fields:", "", "| Field | Accuracy | Coverage | Silent error |", "|---|---|---|---|"]
    fields = sorted(((k, v) for k, v in first.items() if k.startswith("field:")), key=lambda kv: kv[1]["accuracy"])
    for k, s in fields[:6]:
        L.append(f"| {k[6:]} | {pct(s['accuracy'])} | {pct(s['coverage'])} | {pct(s['silent_error'])} |")
    c = m.get("calibration")
    if c:
        L += ["", "### Trained confidence calibration (held-out cases)", "",
              f"Logistic model on inference-time signals, trained on {c['n_train']} fields, tested on {c['n_test']} "
              f"fields from unseen cases.", "",
              "| Score | AUROC (correct vs wrong) | Silent error at same coverage | Precision at same coverage |",
              "|---|---|---|---|",
              f"| Heuristic (OCR conf x validators) | {c['auroc_heuristic']:.3f} | {pct(c['silent_error_heuristic'])} | {pct(c['precision_heuristic'])} |",
              f"| Learned calibrator | {c['auroc_learned']:.3f} | {pct(c['silent_error_learned'])} | {pct(c['precision_learned'])} |",
              "", f"Coverage held at {pct(c['coverage'])} (the heuristic's own answer rate)."]
    v = m["validation"]
    L += ["", "## 2. Pre-submission validation (denial prevention)", "",
          f"- Payor denials in the simulated set: {v['payor_denials']} of {v['cases']} cases",
          f"- Caught before submission: {v['caught_before_submission']} (recall {pct(v['recall'])}, precision {pct(v['precision'])})",
          f"- False blocks (would have been approved): {v['false_blocks']}",
          f"- Missed: {len(v['missed'])} {v['missed']}",
          f"- Rule hits: {v['rule_hits']}", ""]
    if "agents" in m:
        L += ["## 3. Browser agents", "", f"Routing of ready cases: {m['routing']}; held for documentation fixes: {m['held_for_fixes']}", "",
              "| Slice | Runs | Verified submit rate | Mean smoothness | p50 duration | Mean steps | Runs with major QA issue |",
              "|---|---|---|---|---|---|---|"]
        for k, a in m["agents"].items():
            if isinstance(a, dict) and "runs" in a:
                L.append(f"| {k} | {a['runs']} | {pct(a['verified_submit_rate'])} | {a['mean_smoothness']} | "
                         f"{a['p50_duration_s']}s | {a['mean_steps']} | {a['runs_with_major_qa_issue']} |")
        L += ["", f"Error classes: {m['agents']['error_classes']}",
              f"Silent errors (auto-submitted with a major issue): {m['agents']['silent_errors']}",
              f"Portal chaos events: {m['portal_events']}",
              f"Credentials disabled by the pool: {m['credentials']['disabled']}", "",
              "### QA ramp", ""]
        for p, s in m["qa_ramp"].items():
            L.append(f"- **{p}** final human-QA share {s['final_qa_share']:.2f}")
            L += [f"  - {line}" for line in s["log"]]
        L += ["", "### Ablations", "", "| Variant | Runs | Submitted | Lockouts | Error classes |", "|---|---|---|---|---|"]
        for k, a in m["ablations"].items():
            L.append(f"| {k} | {a['n']} | {a['submitted']} | {a.get('lockouts', '-')} | {a['errors']} |")
        f = m["fhir"]
        L += ["", "## 4. Other channels", "",
              f"- FHIR PA API (Da Vinci PAS shape): {f['submitted']}/{f['n']} submitted, p50 {f['p50_s']}s per request",
              f"- Phone agent (IVR, benefits + status): {m['phone']['completed']}/{m['phone']['calls']} calls completed, "
              f"mean {m['phone']['mean_turns']} turns, member-ID repeats after ASR noise: {m['phone']['member_id_repeats']}", ""]
    st = m.get("stats", {})
    if st:
        L += ["## Uncertainty", "", "Small pilots need intervals, so every headline comparison carries one.", ""]
        for arm, e in st.get("extraction", {}).items():
            if arm == "paired":
                L.append(f"- {e['arms'][0]} vs {e['arms'][1]}: field accuracy diff {e['acc_diff']:+.3f} "
                         f"(95% CI {e['ci_doc_bootstrap'][0]:+.3f} to {e['ci_doc_bootstrap'][1]:+.3f}, documents resampled), "
                         f"McNemar p={e['mcnemar_p']} ({e['only_a']} fields right only under {e['arms'][0]}, {e['only_b']} only under {e['arms'][1]})")
            else:
                L.append(f"- {arm}: field accuracy 95% CI {e['field_acc_ci']}, whole-document CI {e['doc_ok_ci']}, "
                         f"silent-error CI {e['silent_error_ci']}")
        for k, a in st.get("ablations", {}).items():
            L.append(f"- {k}: {a['on']} vs {a['off']} submitted, Fisher exact p={a['fisher_p']}")
        if "validation_recall_ci" in st:
            L.append(f"- denial-prevention recall 95% CI {st['validation_recall_ci']}")
        L.append("")
    u = m["llm_usage"]
    L += ["## 5. LLM usage", "", f"{u['calls']} calls, {u['tokens_in']} input / {u['tokens_out']} output tokens, ~${u['cost_usd']}", ""]
    path.write_text("\n".join(L))


if __name__ == "__main__":
    main()
