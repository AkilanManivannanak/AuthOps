"""Evaluate approval outlook, appeal triage and policy drift; write reports/intel.json.

    python scripts/run_intel.py          # offline (no API cost)
    python scripts/run_intel.py --llm    # adds the Claude document agent as the appeal evidence finder (~$2)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from authops.appeals.packet import evaluate as appeals_eval  # noqa: E402
from authops.intel.approval import evaluate as approval_eval  # noqa: E402
from authops.intel.drift import evaluate as drift_eval  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    args = ap.parse_args()
    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M")}
    out["approval"] = {str(t): approval_eval(target=t) for t in (0.7, 0.8, 0.9)}
    for t, e in out["approval"].items():
        print(f"approval target {t}: AUC {e['auc']}")
        for r in e["policies"]:
            print(f"   {r['policy']:32s} full {r['first_pass_full']:.3f} partial {r['partial_rate']:.3f} "
                  f"units {r['units_approved_first_pass']:,} not requested {r['units_left_on_table']:,}")
    out["appeals"] = {"offline": appeals_eval("offline")}
    if args.llm:
        from authops.llm import ClaudeLLM
        llm = ClaudeLLM()
        out["appeals"]["claude"] = appeals_eval("claude", llm)
        out["appeals"]["claude"]["cost_usd"] = round(llm.meter.cost_usd, 2)
    for k, a in out["appeals"].items():
        print(f"appeals [{k}]: triage {a['triage_accuracy']}, to specialist {a['to_specialist']}, "
              f"appeals on correct denials {a['appeals_on_correct_denials']}, wrongful not appealed "
              f"{a['wrongful_denials_not_appealed']}, citations {a['appeal_letters_with_valid_citations']}, "
              f"deciding page cited {a['appeals_citing_the_deciding_page']}")
    out["drift"] = drift_eval()
    print("drift:", {k: v for k, v in out["drift"].items() if k != "threshold_h"})
    (ROOT / "reports" / "intel.json").write_text(json.dumps(out, indent=1, default=str))
    print("wrote reports/intel.json")


if __name__ == "__main__":
    main()
