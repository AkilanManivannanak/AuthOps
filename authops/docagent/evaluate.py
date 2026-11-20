"""Score document-validation arms against the chart answer keys.

The number that matters most is false_pass: a rule the chart fails that the validator
waved through. That request goes to the payor and comes back denied, which is the
outcome Predictive Document Intelligence exists to prevent.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

from authops.docagent.longdoc import CROSS_PAGE, LongChart
from authops.docagent.validators import ChartResult


def bucket(n_pages: int) -> str:
    return "1-40 pages" if n_pages <= 40 else "41-100 pages" if n_pages <= 100 else "100+ pages"


def score(charts: list[LongChart], results: list[ChartResult]) -> dict:
    by_id = {c.chart_id: c for c in charts}
    out: dict = {}
    arms = sorted({r.arm for r in results})
    for arm in arms:
        rs = [r for r in results if r.arm == arm]
        groups: dict[str, list] = defaultdict(list)
        for r in rs:
            c = by_id[r.chart_id]
            for rule, f in r.findings.items():
                truth = c.truth[rule]
                row = (truth, f.verdict)
                groups["all"].append(row)
                groups[bucket(c.n_pages)].append(row)
                groups["cross_page" if rule in CROSS_PAGE else "single_page"].append(row)
                if rule == "R8_medical_necessity":
                    groups["medical_necessity"].append(row)
        summary = {}
        for g, rows in groups.items():
            decided = [(t, v) for t, v in rows if v != "needs_human"]
            fails = [(t, v) for t, v in rows if not t]
            summary[g] = {
                "n": len(rows),
                "coverage": round(len(decided) / len(rows), 3) if rows else 0,
                "accuracy": round(sum((v == "pass") == t for t, v in decided) / len(decided), 3) if decided else 0,
                "catch_rate": round(sum(v == "fail" for t, v in fails) / len(fails), 3) if fails else None,
                "false_pass": sum(v == "pass" for t, v in fails),
                "false_pass_rate": round(sum(v == "pass" for t, v in fails) / len(fails), 3) if fails else 0,
                "false_block": sum(v == "fail" for t, v in rows if t),
            }
        perfect = sum(all((f.verdict == "pass") == by_id[r.chart_id].truth[k] for k, f in r.findings.items())
                      for r in rs)
        out[arm] = {
            "charts": len(rs), "summary": summary,
            "charts_fully_correct": perfect,
            "p50_seconds": round(median(r.seconds for r in rs), 2) if rs else 0,
            "cost_per_chart_usd": round(sum(r.cost_usd for r in rs) / len(rs), 4) if rs else 0,
            "mean_turns": round(sum(r.turns for r in rs) / len(rs), 1) if rs else 0,
            "tokens_in_per_chart": round(sum(r.tokens_in for r in rs) / len(rs)) if rs else 0,
        }
    return out
