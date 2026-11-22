"""Backtest a candidate prompt against production on the same golden documents.

    python scripts/backtest_prompt.py --candidate extract@v2            # vs the production version
    python scripts/backtest_prompt.py --base extract@v1 --candidate extract@v2 --docs 60

Needs ANTHROPIC_API_KEY. Writes one line to reports/prompt_backtests.jsonl and prints the
gate verdict. The candidate is never promoted automatically: change its status in the YAML
after reading the verdict.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from authops.docintel.evaluate import CRITICAL, score  # noqa: E402
from authops.docintel.extract import ClaudeExtractor  # noqa: E402
from authops.docintel.ocr import ocr_pages  # noqa: E402
from authops.llm import ClaudeLLM, UsageMeter  # noqa: E402
from authops.ops import prompts  # noqa: E402
from authops.schemas import DocType  # noqa: E402
from authops.synth.generate import generate_cases  # noqa: E402
from authops.synth.render import render_corpus  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--base", default=None)
    ap.add_argument("--docs", type=int, default=60)
    ap.add_argument("--seed", type=int, default=41, help="golden set seed (held apart from run_all's seed 7)")
    args = ap.parse_args()
    cand = prompts.load(args.candidate)
    base = prompts.load(args.base) if args.base else prompts.production(cand.id)
    data = ROOT / "data" / "golden"
    cases = generate_cases(max(10, args.docs // 2), seed=args.seed, gap_rate=0.3)
    manifest = render_corpus(cases, data)[: args.docs]
    ds = prompts.dataset_fingerprint(manifest)
    print(f"golden set {ds}: {len(manifest)} docs | base {base.ref} ({base.fingerprint}) | "
          f"candidate {cand.ref} ({cand.fingerprint})")
    ocr = {d["doc_id"]: ocr_pages(d["pages"]) for d in manifest}
    results, cost = {}, {}
    for p in (base, cand):
        meter = UsageMeter()
        ex = ClaudeExtractor(ClaudeLLM(p.model, meter), prompt=p)
        t0 = time.time()
        outs = [ex.extract(d["doc_id"], ocr[d["doc_id"]], DocType(d["doc_type"])) for d in manifest]
        results[p.ref] = score(outs, manifest)
        cost[p.ref] = {"usd": round(meter.cost_usd, 3), "seconds": round(time.time() - t0)}
        s = results[p.ref]["summary"]["all"]
        print(f"  {p.ref}: accuracy {s['accuracy']:.3f} silent error {s['silent_error']:.3f} "
              f"docs fully right {s.get('doc_ok', 0):.3f} cost ${meter.cost_usd:.2f}")
    critical = {f for fs in CRITICAL.values() for f in fs}
    verdict = prompts.gate(results[base.ref], results[cand.ref], critical)
    prompts.record(base, cand, ds, verdict, {"cost": cost, "docs": len(manifest)})
    print("PROMOTE" if verdict["promote"] else "BLOCKED", "; ".join(verdict["reasons"]))
    print("field deltas:", {k: v for k, v in verdict["field_deltas"].items() if v})
    print(f"logged to {prompts.LOG}")


if __name__ == "__main__":
    main()
