"""Run the care-readiness evaluations and write reports/care_readiness.json (+ app copy).

    python scripts/run_care_readiness.py            # offline arms only, no API cost
    python scripts/run_care_readiness.py --llm      # adds Claude one-shot vs Claude agent on long charts

The --llm run uses about 30 charts x 2 arms with claude-haiku-4-5 (a few dollars at most).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from authops.benefits.calls import evaluate as bv_evaluate, make_calls  # noqa: E402
from authops.docagent.evaluate import score  # noqa: E402
from authops.docagent.longdoc import make_corpus  # noqa: E402
from authops.docagent.validators import claude_agent, claude_oneshot, offline_agent, offline_oneshot  # noqa: E402
from authops.monitor.panel import compare  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--per-length", type=int, default=6)
    args = ap.parse_args()
    out: dict = {"generated_at": time.strftime("%Y-%m-%d %H:%M")}

    # 1. long-chart document validation
    charts = make_corpus(per_length=args.per_length)
    results = [offline_oneshot(c) for c in charts] + [offline_agent(c) for c in charts]
    if args.llm:
        from authops.llm import ClaudeLLM
        llm = ClaudeLLM()
        for i, c in enumerate(charts):
            for fn in (claude_oneshot, claude_agent):
                try:
                    results.append(fn(c, llm))
                except Exception as e:  # keep the run going; failures are reported
                    print(f"  {fn.__name__} {c.chart_id} failed: {e}")
            print(f"  chart {i + 1}/{len(charts)} ({c.n_pages} pages) done, spend ${llm.meter.cost_usd:.2f}")
        out["llm_model"] = llm.model
    out["docagent"] = score(charts, results)
    out["docagent_corpus"] = {"charts": len(charts), "pages": sorted({c.n_pages for c in charts}),
                              "rules": 8, "failing_rules": sum(not v for c in charts for v in c.truth.values())}
    # per-chart detail for the app
    out["docagent_detail"] = [{"chart": r.chart_id, "arm": r.arm, "seconds": round(r.seconds, 2),
                               "turns": r.turns, "cost": round(r.cost_usd, 4),
                               "findings": {k: [f.verdict, f.pages, f.quote[:300], f.reason[:200], f.raw_verdict]
                                            for k, f in r.findings.items()}} for r in results]

    # 2. coverage monitoring, 5 seeds
    runs = [compare(n=200, seed=s) for s in range(1, 6)]
    pols = ("reactive", "scheduled", "proactive")
    out["monitor"] = {p: {k: round(mean(r[p][k] for r in runs), 1) for k in
                          ("visits", "denied_visits", "denied_dollars", "days_without_valid_auth", "reauths",
                           "eligibility_checks", "alerts")} for p in pols}
    for p in pols:
        vals = [1 - r[p]["denied_dollars"] / r["reactive"]["denied_dollars"] for r in runs]
        out["monitor"][p]["denied_dollars_cut_vs_reactive"] = [round(min(vals), 3), round(mean(vals), 3), round(max(vals), 3)]
        prec = [r[p]["alert_precision"] for r in runs if r[p]["alert_precision"] is not None]
        out["monitor"][p]["alert_precision"] = round(mean(prec), 3) if prec else None
        causes: dict = {}
        for r in runs:
            for k, v in r[p]["by_cause"].items():
                causes[k] = causes.get(k, 0) + v / len(runs)
        out["monitor"][p]["by_cause"] = {k: round(v) for k, v in causes.items()}
    out["monitor_panel"] = runs[0]["panel"] | {"seeds": 5}

    # 3. benefits calls
    out["benefits"] = bv_evaluate(make_calls(n=120))

    rep = ROOT / "reports" / "care_readiness.json"
    rep.parent.mkdir(exist_ok=True)
    rep.write_text(json.dumps(out, indent=2, default=str))
    (ROOT / "app" / "assets").mkdir(parents=True, exist_ok=True)
    shutil.copy(rep, ROOT / "app" / "assets" / "care_readiness.json")

    for arm, v in out["docagent"].items():
        a = v["summary"]["all"]
        print(f"{arm:16s} acc {a['accuracy']:.3f} cov {a['coverage']:.3f} false-pass {a['false_pass']} "
              f"charts-correct {v['charts_fully_correct']}/{v['charts']} p50 {v['p50_seconds']}s ${v['cost_per_chart_usd']}")
    for p in pols:
        m = out["monitor"][p]
        print(f"{p:10s} denied ${m['denied_dollars']:,.0f}  cut vs reactive {m['denied_dollars_cut_vs_reactive']}")
    for arm, v in out["benefits"].items():
        print(f"{arm:17s} field acc {v['field_accuracy']}  fluent-wrong {v['fluent_wrong_fields']}  est err ${v['estimate_abs_error_mean']}")
    print(f"wrote {rep}")


if __name__ == "__main__":
    main()
