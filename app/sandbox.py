"""Live sandbox for the app: synthetic cases, rendered documents, mock portals, browser agent.

The portal server starts once per app process. Each agent run gets its own browser in a
worker thread (Playwright's sync API must not share Streamlit's script thread), and
streams steps back through a queue so the page can draw them as they happen.
"""
from __future__ import annotations

import os
import queue
import shutil
import tempfile
import threading
from datetime import date
from pathlib import Path

import streamlit as st

from authops.portals.app import CREDENTIALS, Chaos

TODAY = date(2026, 11, 17)


def chrome_path() -> str | None:
    for p in [os.environ.get("AUTHOPS_CHROME"), "/usr/bin/chromium", "/usr/bin/chromium-browser",
              "/usr/bin/google-chrome"]:
        if p and Path(p).exists():
            return p
    return None


def browser_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    if chrome_path():
        return True
    return any(Path.home().glob(".cache/ms-playwright/chromium*"))


@st.cache_resource(show_spinner="Setting up the sandbox: generating patients and documents...")
def sandbox():
    from authops.synth.generate import generate_cases
    from authops.synth.render import render_corpus

    d = Path(tempfile.mkdtemp(prefix="authops_"))
    cases = generate_cases(40, seed=31, today=TODAY, gap_rate=0.0)
    render_corpus(cases, d, conditions=("clean",))
    return {"dir": d, "cases": [c.model_dump(mode="json") for c in cases]}


@st.cache_resource(show_spinner="Starting the sandbox payor portals...")
def portal_server():
    from authops.portals.server import PortalServer

    sb = sandbox()
    chaos = Chaos()
    srv = PortalServer(sb["dir"] / "cases.json", chaos)
    srv.__enter__()
    return srv, chaos


def case_files(case_id: str) -> list[str]:
    return [str(sandbox()["dir"] / "docs" / f"{case_id}_treatment_plan.pdf")]


def start_agent_run(case: dict, portal: str, chaos_cfg: dict, guard: bool, threshold: int,
                    spec: dict | None = None, wall_clock_s: float = 60) -> tuple[queue.Queue, threading.Thread]:
    """Run one agent in a worker thread. Queue yields ('step', dict, jpeg) ... then ('done', result)."""
    q: queue.Queue = queue.Queue()
    srv, chaos = portal_server()

    def work():
        try:
            from playwright.sync_api import sync_playwright

            from authops.agent.credentials import CredentialPool
            from authops.agent.policy import PlaybookPolicy
            from authops.agent.runtime import AgentRuntime
            from authops.ops.store import Store

            for k, v in {"northwind_release": "", **chaos_cfg}.items():   # a release is per run, never sticky
                setattr(chaos, k, v)
            srv.state.summit_locked.clear()
            srv.state.summit_fail.clear()
            db = Path(tempfile.gettempdir()) / "authops_app_runs.db"
            with sync_playwright() as p:
                exe = chrome_path()
                b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"],
                                      **({"executable_path": exe} if exe else {}))
                pool = CredentialPool(CREDENTIALS, threshold=threshold)
                rt = AgentRuntime(b, srv.url, pool, Store(db), overlay_guard=guard, wall_clock_s=wall_clock_s)
                r = rt.run(case, portal, PlaybookPolicy(portal, spec), case_files(case["case_id"]),
                           arm="app", on_step=lambda s, shot: q.put(("step", s, shot)))
                b.close()
            locks = sum(1 for e in srv.state.events if e[0] == "lockout")
            q.put(("done", {"status": r.status, "error_class": r.error_class, "note": r.note, "ref": r.ref,
                            "verified": r.verified, "smoothness": r.smoothness, "steps": r.steps,
                            "duration_s": r.duration_s, "counts": r.counts, "credentials": pool.status(),
                            "lockouts_total": locks}, None))
        except Exception as e:  # surface, never hang the page
            q.put(("error", repr(e)[:400], None))

    t = threading.Thread(target=work, daemon=True)
    t.start()
    return q, t


def cleanup():  # pragma: no cover
    shutil.rmtree(sandbox()["dir"], ignore_errors=True)
