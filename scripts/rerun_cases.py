"""Re-run chosen cases on one portal with one policy, printing every step (for debugging a failure).

    python scripts/rerun_cases.py keystone claude PA-0023 PA-0057
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from authops.agent.credentials import CredentialPool  # noqa: E402
from authops.agent.policy import ClaudePolicy, PlaybookPolicy  # noqa: E402
from authops.agent.runtime import AgentRuntime  # noqa: E402
from authops.llm import ClaudeLLM  # noqa: E402
from authops.ops.store import Store  # noqa: E402
from authops.portals.app import CREDENTIALS, Chaos  # noqa: E402
from authops.portals.server import PortalServer  # noqa: E402

portal, which, ids = sys.argv[1], sys.argv[2], sys.argv[3:]
cases = {c["case_id"]: c for c in json.loads((ROOT / "data" / "cases.json").read_text())}
with PortalServer(ROOT / "data" / "cases.json", Chaos()) as srv, sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    rt = AgentRuntime(b, srv.url, CredentialPool(CREDENTIALS), Store(ROOT / "reports" / "rerun.db"))
    for cid in ids:
        pol = ClaudePolicy(portal, ClaudeLLM("claude-haiku-4-5")) if which == "claude" else PlaybookPolicy(portal)
        r = rt.run(cases[cid], portal, pol, [str(ROOT / "data" / "docs" / f"{cid}_treatment_plan.pdf")],
                   on_step=lambda s, _: print(f"  {s['idx']:2d} {s['kind']:8s} {s['tool']:18s} "
                                              f"{'ok ' if s['ok'] else 'ERR'} {s['detail'][:110]}"))
        print(cid, r.status, r.error_class, r.note)
    b.close()
