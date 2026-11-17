"""Agent runtime: the observe-act loop with guards, limits, persistence and verification.

Controls modeled on what Silna published for production browser agents:
  * hard limits: 50-turn cap and a wall-clock budget per session; a timeout is a
    signal to change the prompt, model or tools, not something to retry blindly
  * every policy decision and every tool execution is persisted as its own step
  * overlay guard before actions; occluded-element errors trigger it automatically
  * failure classification: bad credential, lockout, session kick, transient 5xx,
    form validation, element not found, loop
  * credential leasing with consecutive-failure disabling (prevents lockouts)
  * loop detection on (page state, action) repeats
  * hard stop after submission, then confirmation verification against the case
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

from authops.agent.credentials import CredentialPool
from authops.agent.tools import ToolError, ToolResult, Tools
from authops.ops.scoring import smoothness
from authops.ops.store import Store

MAX_TURNS = 50
WALL_CLOCK_S = 120


@dataclass
class RunResult:
    run_id: str
    case_id: str
    portal: str
    arm: str
    status: str = "running"  # submitted | needs_human | failed
    error_class: str = ""
    ref: str | None = None
    verified: bool = False
    steps: int = 0
    counts: dict = field(default_factory=dict)
    smoothness: float = 0.0
    duration_s: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    note: str = ""


def classify_page(obs) -> str:
    text = (" ".join(obs.errors) + " " + obs.text[:600]).lower()
    if obs.status and obs.status >= 500:
        return "transient_5xx"
    if "account locked" in text:
        return "account_locked"
    if "signed in elsewhere" in text:
        return "session_kicked"
    if "invalid credentials" in text or "invalid username or password" in text or "login failed" in text:
        return "auth_invalid"
    if "session expired" in text:
        return "session_expired"
    if obs.errors:
        return "form_validation"
    return ""


class AgentRuntime:
    def __init__(self, browser, base_url: str, pool: CredentialPool, store: Store,
                 max_turns: int = MAX_TURNS, wall_clock_s: float = WALL_CLOCK_S,
                 overlay_guard: bool = True):
        self.browser = browser
        self.base_url = base_url
        self.pool = pool
        self.store = store
        self.max_turns = max_turns
        self.wall_clock_s = wall_clock_s
        self.overlay_guard = overlay_guard  # ablation switch

    def run(self, case: dict, portal: str, policy, files: list[str], arm: str = "default",
            qa_routed: bool = False, on_step=None) -> RunResult:
        """`on_step(step_dict, jpeg_bytes)` is called after every persisted step (used by the UI)."""
        run_id = uuid.uuid4().hex[:10]
        res = RunResult(run_id, case["case_id"], portal, arm)
        c = res.counts
        bump = lambda k, n=1: c.__setitem__(k, c.get(k, 0) + n)  # noqa: E731
        self.store.start_run(run_id, case_id=case["case_id"], portal=portal, channel="portal", arm=arm,
                             policy=policy.name, model=policy.model or "", status="running",
                             qa_routed=int(qa_routed))
        cred = self.pool.lease(portal)
        if cred is None:
            return self._end(res, "needs_human", "no_credential", "all credentials disabled or leased", 0, policy)
        context = self.browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        ctx = {"case": case, "files": files, "credential": cred}
        tools = Tools(page, ctx, self.base_url)
        t0 = time.time()
        history: list[dict] = []
        seen: dict[str, int] = {}
        step = 0
        submitted = False
        login_attempts = 0
        transient = 0

        def persist(kind, tool, args, r: ToolResult, dur):
            nonlocal step
            step += 1
            self.store.step(run_id, step, kind, tool, args, r.ok, r.error_class, r.detail, page.url, dur)
            history.append({"tool": tool, "args": args, "ok": r.ok, "error_class": r.error_class,
                            "detail": r.detail})
            if on_step is not None:
                try:
                    shot = page.screenshot(type="jpeg", quality=55)
                except Exception:
                    shot = None
                on_step({"idx": step, "kind": kind, "tool": tool, "args": args, "ok": r.ok,
                         "error_class": r.error_class, "detail": r.detail, "url": page.url,
                         "counts": dict(c)}, shot)

        try:
            persist("tool", "goto", {"path": policy.start}, tools.goto(policy.start), 0)
            for _turn in range(self.max_turns):
                if time.time() - t0 > self.wall_clock_s:
                    bump("timeout")
                    return self._finish(res, "failed", "timeout", "wall clock exceeded", step, policy, t0, c)
                obs = tools.observe()
                # ---------------- page-level classification and recovery
                pc = classify_page(obs)
                if pc == "account_locked":
                    self.pool.report(cred, False, "locked")
                    self.store.event("credential_locked", cred.username, portal)
                    return self._finish(res, "needs_human", "account_locked", "portal locked the account",
                                        step, policy, t0, c)
                if pc == "auth_invalid" and history and history[-1]["tool"] == "type_credential":
                    login_attempts += 1
                    self.pool.report(cred, False, "auth_invalid")
                    if cred.disabled:
                        self.store.event("credential_disabled", cred.username,
                                         f"{cred.consecutive_failures} consecutive login failures")
                    nxt = self.pool.lease(portal, exclude={cred.username})
                    self.pool.release(cred)
                    if nxt is None or login_attempts > 3:
                        return self._finish(res, "needs_human", "auth_invalid", "no working credential",
                                            step, policy, t0, c)
                    cred = nxt
                    ctx["credential"] = cred
                    bump("credential_swap")
                    persist("guard", "swap_credential", {"to": cred.username}, ToolResult(True, "swapped"), 0)
                elif pc == "transient_5xx":
                    transient += 1
                    bump("retry")
                    if transient > 3:
                        return self._finish(res, "failed", "transient_5xx", "payor kept failing",
                                            step, policy, t0, c)
                    time.sleep(0.5 * 2 ** transient)
                    page.go_back()
                    if hasattr(policy, "reset_page"):
                        policy.reset_page()  # same URL as before the 503, so replay this page's steps
                    seen.clear()  # a deliberate replay after a 5xx is not a logic loop
                    persist("guard", "backoff_resubmit", {"attempt": transient},
                            ToolResult(True, "went back to resubmit"), 0)
                    submitted = False
                    continue
                elif pc == "session_kicked":
                    bump("retry")
                if obs.dialogs and self.overlay_guard:
                    r = tools.dismiss_overlays()
                    bump("guard")
                    persist("guard", "dismiss_overlays", {}, r, 0)
                    obs = tools.observe()

                # ---------------- policy decision
                t1 = time.perf_counter()
                act = policy.next_action(obs, ctx, history)
                ti, to = act.pop("_tokens", (0, 0))
                res.tokens_in += ti
                res.tokens_out += to
                tool, args = act.get("tool"), act.get("args", {})
                if tool == "invalid":
                    bump("invalid_action")
                    persist("decision", "invalid", args, ToolResult(False, "invalid action", "invalid_action"),
                            (time.perf_counter() - t1) * 1000)
                    continue
                key = obs.state_hash() + json.dumps([tool, args], sort_keys=True, default=str)
                seen[key] = seen.get(key, 0) + 1
                if seen[key] >= 3:
                    bump("loop")
                    return self._finish(res, "needs_human", "logic_loop", f"repeated {tool} on same page",
                                        step, policy, t0, c)
                if tool == "finish":
                    status = args.get("status", "needs_human")
                    if status == "submitted" and not submitted:
                        status, note = "needs_human", "finish(submitted) without a submit action"
                    else:
                        note = args.get("note", "")
                    if status == "submitted":
                        return self._verify_and_finish(res, tools, case, step, policy, t0, c)
                    err = classify_page(obs) or "playbook_gap"
                    return self._finish(res, status, err, note, step, policy, t0, c)

                # ---------------- execute with one guarded retry
                r = self._execute(tools, tool, args)
                if not r.ok and r.error_class in ("occluded", "element_not_found", "timeout"):
                    bump("retry")
                    if r.error_class == "occluded" and self.overlay_guard:
                        bump("guard")
                        tools.dismiss_overlays()
                    else:
                        tools.wait(600)
                    r = self._execute(tools, tool, args)
                persist("tool", tool, args, r, (time.perf_counter() - t1) * 1000)
                if r.ok and tool == "fill" and r.data and "shown" in r.data:
                    bump("drift")  # field did not keep what we typed (mask, maxlength, formatter)
                if r.ok and act.get("submit"):
                    submitted = True
                if tool == "read_confirmation" and r.ok:
                    ctx["confirmation"] = r.data
            bump("loop")
            return self._finish(res, "failed", "turn_cap", f"hit {self.max_turns}-turn cap", step, policy, t0, c)
        except Exception as e:  # infrastructure failure: record, never hide
            return self._finish(res, "failed", "runtime_error", repr(e)[:300], step, policy, t0, c)
        finally:
            self.pool.release(cred)
            context.close()

    def _execute(self, tools: Tools, tool: str, args: dict) -> ToolResult:
        try:
            if tool == "answer":
                q = tools.query_document(args["target"])
                if not q.ok:
                    return q
                ans = q.data["answer"]
                inner = tools.select if args.get("kind") == "select" else tools.fill
                r = inner(args["target"], ans)
                return ToolResult(r.ok, f"{r.detail} (answer '{ans}' from {q.data['evidence']})")
            fn = getattr(tools, tool, None)
            if fn is None:
                return ToolResult(False, f"unknown tool {tool}", "unknown_tool")
            return fn(**args)
        except ToolError as e:
            return ToolResult(False, e.detail, e.error_class)
        except TypeError as e:
            return ToolResult(False, f"bad arguments: {e}", "bad_args")
        except Exception as e:
            cls = "timeout" if "Timeout" in type(e).__name__ else "tool_exception"
            return ToolResult(False, str(e).splitlines()[0][:200], cls)

    def _verify_and_finish(self, res, tools, case, step, policy, t0, c):
        conf = tools.ctx.get("confirmation")
        if not conf:
            try:
                conf = tools.read_confirmation().data
            except ToolError:
                conf = None
        if not conf:
            return self._finish(res, "needs_human", "no_confirmation", "submitted but no reference number",
                                step, policy, t0, c)
        p = case["patient"]
        checks = {
            "patient": conf.get("patient", "").lower() == f"{p['first_name']} {p['last_name']}".lower(),
            "member": conf.get("member", "") == p["member_id"],
            "cpt": sorted(x.strip() for x in conf.get("cpt", "").split(",") if x.strip()) == sorted(case["cpt_codes"]),
        }
        res.ref = conf.get("ref")
        res.verified = all(checks.values())
        if not res.verified:
            c["verification_mismatch"] = c.get("verification_mismatch", 0) + 1
            bad = [k for k, ok in checks.items() if not ok]
            return self._finish(res, "needs_human", "verification_mismatch", f"confirmation mismatch: {bad}",
                                step, policy, t0, c)
        return self._finish(res, "submitted", "", f"ref {res.ref}", step, policy, t0, c)

    def _finish(self, res, status, err, note, step, policy, t0, c):
        res.status, res.error_class, res.note, res.steps = status, err, note, step
        res.duration_s = round(time.time() - t0, 2)
        res.smoothness = smoothness(c, step, getattr(policy, "expected_steps", 20))
        self.store.update_run(res.run_id, ended=time.time(), status=status, outcome=status, ref=res.ref,
                              steps=step, retries=c.get("retry", 0), smoothness=res.smoothness,
                              verified=int(res.verified), error_class=err, tokens_in=res.tokens_in,
                              tokens_out=res.tokens_out, notes=note[:500])
        return res

    def _end(self, res, status, err, note, step, policy):
        res.status, res.error_class, res.note = status, err, note
        self.store.update_run(res.run_id, status=status, error_class=err, notes=note)
        return res
